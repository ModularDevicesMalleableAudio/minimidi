//! minimidi — minimal Linux ALSA Raw MIDI output.
//!
//! Public surface: RawMidiOut, list_cards(), find_card(), MinimidiError.
//! Channels are 1-indexed (1..=16) at the API boundary and converted to the
//! 0..=15 status nibble internally.

use pyo3::create_exception;
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyType};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;

create_exception!(_minimidi, MinimidiError, pyo3::exceptions::PyException);

// ---- Validation (pure core + PyErr adapters) -------------------------------
//
// The check_* functions are pure (no PyO3 runtime types reachable), so the
// #[cfg(test)] module exercises them without linking libpython — required by
// the CI rust job, which runs `cargo test` with no Python toolchain.

fn check_channel(channel: i32) -> Result<u8, String> {
    if !(1..=16).contains(&channel) {
        return Err(format!("channel must be 1..=16, got {channel}"));
    }
    Ok((channel - 1) as u8) // → MIDI's 0..15 channel nibble
}

fn check_data_byte(value: i32, name: &str) -> Result<u8, String> {
    if !(0..=127).contains(&value) {
        return Err(format!("{name} must be 0..=127, got {value}"));
    }
    Ok(value as u8)
}

fn validate_channel(channel: i32) -> PyResult<u8> {
    check_channel(channel).map_err(MinimidiError::new_err)
}

fn validate_data_byte(value: i32, name: &str) -> PyResult<u8> {
    check_data_byte(value, name).map_err(MinimidiError::new_err)
}

// ---- Card lookup ------------------------------------------------------------

/// Pure parser — takes the file contents directly. Fully unit-testable from
/// Rust without touching the filesystem.
///
/// /proc/asound/cards format (continuation lines carry the long name):
/// ```text
///  10 [VirMIDI        ]: VirMIDI - VirMIDI
///                        Virtual MIDI Card 1
/// ```
/// We grab the leading index and the bracketed id, trimming ALSA's bracket
/// padding. Malformed lines are skipped, never an error.
fn parse_cards_content(raw: &str) -> Vec<(i32, String)> {
    let mut cards = Vec::new();
    for line in raw.lines() {
        if let Some((num, rest)) = line.trim_start().split_once(' ') {
            if let Ok(n) = num.parse::<i32>() {
                if let Some(start) = rest.find('[') {
                    if let Some(end) = rest[start + 1..].find(']') {
                        let id = rest[start + 1..start + 1 + end].trim().to_string();
                        cards.push((n, id));
                    }
                }
            }
        }
    }
    cards
}

/// Thin I/O wrapper around the pure parser. A missing /proc/asound/cards
/// (host without ALSA: minimal containers, CI runners) means "zero cards",
/// not an error — so find_card() reports the card as not found instead of
/// leaking a FileNotFoundError about an internal path. Other I/O errors
/// still propagate.
fn parse_cards() -> std::io::Result<Vec<(i32, String)>> {
    match std::fs::read_to_string("/proc/asound/cards") {
        Ok(raw) => Ok(parse_cards_content(&raw)),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Vec::new()),
        Err(e) => Err(e),
    }
}

#[pyfunction]
fn list_cards() -> PyResult<Vec<(i32, String)>> {
    // PyErr::from(io::Error) preserves errno-derived exception subclasses.
    parse_cards().map_err(PyErr::from)
}

#[pyfunction]
fn find_card(card_id: &str) -> PyResult<i32> {
    let cards = parse_cards().map_err(PyErr::from)?;
    // Exact, case-sensitive match against the parsed (padding-trimmed) id.
    // Duplicates resolve to the first match, in /proc file order.
    cards
        .iter()
        .find(|(_, id)| id == card_id)
        .map(|(n, _)| *n)
        .ok_or_else(|| {
            MinimidiError::new_err(format!(
                "ALSA card '{card_id}' not found in /proc/asound/cards"
            ))
        })
}

// ---- RawMidiOut ---------------------------------------------------------------

/// A write-only Linux ALSA Raw MIDI output port.
#[pyclass]
struct RawMidiOut {
    // Mutex makes the port safe to share across Python threads; the fd is
    // wrapped in an Option so close() can drop it without consuming self.
    // The mutex is acquired *inside* detach (see write() below) so a
    // contending thread blocks without holding the GIL.
    file: Mutex<Option<File>>,
    #[pyo3(get)]
    card_id: String,
    #[pyo3(get)]
    device: i32,
}

#[pymethods]
impl RawMidiOut {
    #[new]
    #[pyo3(signature = (card_id, device=0))]
    fn new(card_id: String, device: i32) -> PyResult<Self> {
        if device < 0 {
            return Err(MinimidiError::new_err(format!(
                "device must be >= 0, got {device}"
            )));
        }
        // No upper bound on device — a non-existent /dev/snd/midiC*D* path
        // surfaces as FileNotFoundError from open(2), which is the right
        // error in that situation.
        let card_num = find_card(&card_id)?;
        let path: PathBuf = format!("/dev/snd/midiC{card_num}D{device}").into();
        // PyErr::from(io::Error) preserves errno subclasses
        // (FileNotFoundError, PermissionError, ...).
        let file = OpenOptions::new()
            .write(true)
            .open(&path)
            .map_err(PyErr::from)?;
        Ok(Self {
            file: Mutex::new(Some(file)),
            card_id,
            device,
        })
    }

    /// Test-only constructor: open `path` directly, bypassing card lookup.
    /// Underscore-prefixed and absent from the .pyi stubs, so consumers
    /// under `mypy --strict` cannot accidentally depend on it. Used by the
    /// test suite to point a RawMidiOut at a temp-file/FIFO fake without
    /// requiring `snd-virmidi`. Not part of the stable API.
    #[classmethod]
    fn _open_path(_cls: &Bound<'_, PyType>, path: &str) -> PyResult<Self> {
        let file = OpenOptions::new()
            .write(true)
            .open(path)
            .map_err(PyErr::from)?;
        Ok(Self {
            file: Mutex::new(Some(file)),
            card_id: "<custom>".to_string(),
            device: -1,
        })
    }

    #[getter]
    fn is_open(&self) -> bool {
        self.file
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .is_some()
    }

    fn note_on(&self, py: Python<'_>, channel: i32, note: i32, velocity: i32) -> PyResult<()> {
        let ch = validate_channel(channel)?;
        let n = validate_data_byte(note, "note")?;
        let v = validate_data_byte(velocity, "velocity")?;
        self.write(py, &[0x90 | ch, n, v])
    }

    fn note_off(&self, py: Python<'_>, channel: i32, note: i32) -> PyResult<()> {
        let ch = validate_channel(channel)?;
        let n = validate_data_byte(note, "note")?;
        self.write(py, &[0x80 | ch, n, 0])
    }

    fn cc(&self, py: Python<'_>, channel: i32, controller: i32, value: i32) -> PyResult<()> {
        let ch = validate_channel(channel)?;
        let c = validate_data_byte(controller, "controller")?;
        let v = validate_data_byte(value, "value")?;
        self.write(py, &[0xB0 | ch, c, v])
    }

    fn send_bytes(&self, py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<()> {
        // Strict type check: only `bytes` is accepted. `bytearray`,
        // `memoryview`, `str`, list[int] etc. all raise TypeError. The
        // type check precedes the length check so type errors take
        // priority. v0.1 ships bytes-only deliberately; relaxing it
        // later would be non-breaking.
        let bytes = data.cast::<PyBytes>().map_err(|_| {
            PyTypeError::new_err(
                "send_bytes: data must be `bytes` (not bytearray, memoryview, str, or list)",
            )
        })?;
        let slice: &[u8] = bytes.as_bytes();
        if slice.is_empty() || slice.len() > 1024 {
            return Err(MinimidiError::new_err(format!(
                "send_bytes: length must be 1..=1024, got {}",
                slice.len()
            )));
        }
        self.write(py, slice)
    }

    fn close(&self) -> PyResult<()> {
        let mut guard = self.file.lock().unwrap_or_else(|e| e.into_inner());
        *guard = None; // Drop closes the fd. Idempotent: already-None stays None.
        Ok(())
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __exit__(
        &self,
        _exc_type: &Bound<'_, PyAny>,
        _exc_val: &Bound<'_, PyAny>,
        _exc_tb: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        self.close()?;
        Ok(false) // don't suppress exceptions
    }

    fn __repr__(&self) -> String {
        let state = if self.is_open() { "open" } else { "closed" };
        format!(
            "<minimidi.RawMidiOut card_id='{}' device={} {}>",
            self.card_id, self.device, state
        )
    }
}

// Non-pymethods impl block for private helpers.
impl RawMidiOut {
    fn write(&self, py: Python<'_>, bytes: &[u8]) -> PyResult<()> {
        // Release the GIL *before* taking the mutex, so a thread contending
        // for the same port blocks on the mutex without holding the GIL.
        // Mutex poisoning is ignored: write_all is the only operation under
        // the lock and doesn't panic in normal use.
        //
        // Write errors do NOT mutate port state (deliberate design decision):
        // is_open stays true and a retry surfaces the real OS error again.
        py.detach(|| {
            let mut guard = self.file.lock().unwrap_or_else(|e| e.into_inner());
            let file = guard
                .as_mut()
                .ok_or_else(|| MinimidiError::new_err("write on closed RawMidiOut"))?;
            file.write_all(bytes).map_err(PyErr::from)
        })
    }
}

// ---- Module entrypoint ---------------------------------------------------------

#[pymodule]
fn _minimidi(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RawMidiOut>()?;
    m.add_function(wrap_pyfunction!(list_cards, m)?)?;
    m.add_function(wrap_pyfunction!(find_card, m)?)?;
    m.add("MinimidiError", m.py().get_type::<MinimidiError>())?;
    Ok(())
}

// ---- Tests (pure: no libpython needed; CI rust job has no Python) --------------

#[cfg(test)]
mod tests {
    use super::*;

    // -- byte patterns --

    #[test]
    fn note_on_byte_pattern() {
        // Channel 1 = nibble 0; channel 16 = nibble F.
        let ch = check_channel(1).unwrap();
        assert_eq!([0x90 | ch, 60, 100], [0x90, 60, 100]);

        let ch = check_channel(16).unwrap();
        assert_eq!([0x90 | ch, 60, 100], [0x9F, 60, 100]);
    }

    #[test]
    fn note_off_byte_pattern() {
        let ch = check_channel(1).unwrap();
        assert_eq!([0x80 | ch, 60, 0], [0x80, 60, 0]);

        let ch = check_channel(16).unwrap();
        assert_eq!([0x80 | ch, 127, 0], [0x8F, 127, 0]);
    }

    #[test]
    fn cc_byte_pattern() {
        let ch = check_channel(1).unwrap();
        assert_eq!([0xB0 | ch, 74, 64], [0xB0, 74, 64]);

        let ch = check_channel(16).unwrap();
        assert_eq!([0xB0 | ch, 74, 64], [0xBF, 74, 64]);
    }

    // -- validation boundaries --

    #[test]
    fn channel_out_of_range_rejected() {
        assert!(check_channel(0).is_err());
        assert!(check_channel(17).is_err());
        assert!(check_channel(-1).is_err());
    }

    #[test]
    fn channel_boundaries_accepted() {
        assert_eq!(check_channel(1).unwrap(), 0x0);
        assert_eq!(check_channel(16).unwrap(), 0xF);
    }

    #[test]
    fn data_byte_out_of_range_rejected() {
        assert!(check_data_byte(-1, "x").is_err());
        assert!(check_data_byte(128, "x").is_err());
        assert!(check_data_byte(255, "x").is_err());
    }

    #[test]
    fn data_byte_boundaries_accepted() {
        assert_eq!(check_data_byte(0, "x").unwrap(), 0);
        assert_eq!(check_data_byte(127, "x").unwrap(), 127);
    }

    #[test]
    fn error_messages_name_the_argument() {
        assert!(check_channel(0).unwrap_err().contains("channel"));
        assert!(check_data_byte(128, "velocity")
            .unwrap_err()
            .contains("velocity"));
    }

    // -- /proc/asound/cards parser --

    const TYPICAL: &str = "\
 0 [PCH            ]: HDA-Intel - HDA Intel PCH
                      HDA Intel PCH at 0xaeb94000 irq 174
 3 [pisound        ]: pisound - pisound
                      pisound
10 [VirMIDI        ]: VirMIDI - VirMIDI
                      Virtual MIDI Card 1
";

    #[test]
    fn parse_cards_handles_typical_proc_format() {
        let cards = parse_cards_content(TYPICAL);
        assert_eq!(
            cards,
            vec![
                (0, "PCH".to_string()),
                (3, "pisound".to_string()),
                (10, "VirMIDI".to_string()), // multi-digit index
            ]
        );
    }

    #[test]
    fn parse_cards_ignores_malformed_lines() {
        let malformed = "\
not a card line at all
 5 no brackets here
 6 [Unclosed : bracket never ends
x [BadIndex       ]: nope - nope

 7 [Good           ]: ok - ok
";
        assert_eq!(
            parse_cards_content(malformed),
            vec![(7, "Good".to_string())]
        );
    }

    #[test]
    fn parse_cards_empty_input_yields_no_cards() {
        assert_eq!(parse_cards_content(""), vec![]);
    }

    #[test]
    fn parse_cards_trims_bracket_padding_but_preserves_inner_id_case() {
        let cards = parse_cards_content(" 2 [MixedCase      ]: x - x\n");
        assert_eq!(cards, vec![(2, "MixedCase".to_string())]);
    }

    #[test]
    fn duplicate_card_ids_keep_proc_order() {
        let dup = "\
 1 [Twin           ]: x - x
 2 [Twin           ]: y - y
";
        // find_card() resolves duplicates to the first match via .find(),
        // so parse order must be /proc file order.
        let cards = parse_cards_content(dup);
        assert_eq!(
            cards,
            vec![(1, "Twin".to_string()), (2, "Twin".to_string())]
        );
        let first = cards.iter().find(|(_, id)| id == "Twin").map(|(n, _)| *n);
        assert_eq!(first, Some(1));
    }
}
