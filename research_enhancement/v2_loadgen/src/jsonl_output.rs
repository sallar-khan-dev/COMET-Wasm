use anyhow::{Context, Result};
use std::fs::OpenOptions;
use std::io::{BufWriter, Write};
use std::path::Path;

use crate::request_record::RequestRecord;

pub fn write_jsonl(path: &Path, records: &[RequestRecord]) -> Result<()> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .with_context(|| format!("Cannot create JSONL output: {}", path.display()))?;

    let mut writer = BufWriter::new(file);

    for record in records {
        serde_json::to_writer(&mut writer, record).context("Failed to serialize request record")?;

        writer
            .write_all(b"\n")
            .context("Failed to write JSONL newline")?;
    }

    writer.flush().context("Failed to flush JSONL output")?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn writes_one_line_per_request_and_rejects_overwrite() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();

        let path = std::env::temp_dir().join(format!(
            "comet_v2_jsonl_{}_{}.jsonl",
            std::process::id(),
            unique
        ));

        let records = vec![
            RequestRecord::new(0, "v2-00000000".into(), 0, "lr".into(), 1, 0),
            RequestRecord::new(1, "v2-00000001".into(), 1, "lr".into(), 0, 1000),
        ];

        write_jsonl(&path, &records).unwrap();

        let content = std::fs::read_to_string(&path).unwrap();
        let lines: Vec<&str> = content.lines().collect();

        assert_eq!(lines.len(), 2);

        let first: serde_json::Value = serde_json::from_str(lines[0]).unwrap();
        let second: serde_json::Value = serde_json::from_str(lines[1]).unwrap();

        assert_eq!(first["sequence"], 0);
        assert_eq!(first["request_id"], "v2-00000000");
        assert_eq!(second["sequence"], 1);
        assert_eq!(second["request_id"], "v2-00000001");

        assert!(write_jsonl(&path, &records).is_err());

        std::fs::remove_file(&path).unwrap();
    }
}
