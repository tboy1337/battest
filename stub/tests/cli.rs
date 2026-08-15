//! Integration tests that run the battest-stub binary like PATH mocks do.

use std::env;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

static TEST_DIR_SEQ: AtomicU64 = AtomicU64::new(0);

fn make_temp_dir() -> PathBuf {
    let seq = TEST_DIR_SEQ.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |value| value.as_nanos());
    let path = env::temp_dir().join(format!(
        "battest-stub-cli-{}-{seq}-{nanos}",
        std::process::id()
    ));
    fs::create_dir_all(&path).expect("create temp dir");
    path
}

fn remove_temp_dir(path: &Path) {
    let _ = fs::remove_dir_all(path);
    for _ in 0..20 {
        if !path.exists() {
            return;
        }
        let _ = fs::remove_dir_all(path);
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
}

fn stub_binary() -> PathBuf {
    for key in ["CARGO_BIN_EXE_battest_stub", "CARGO_BIN_EXE_battest-stub"] {
        if let Ok(path) = env::var(key) {
            return PathBuf::from(path);
        }
    }
    let mut candidate = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    candidate.push("target");
    candidate.push("debug");
    if cfg!(windows) {
        candidate.push("battest-stub.exe");
    } else {
        candidate.push("battest-stub");
    }
    candidate
}

const ETXTBSY_ATTEMPTS: u32 = 8;

fn is_etxtbsy(err: &io::Error) -> bool {
    err.kind() == io::ErrorKind::ExecutableFileBusy || err.raw_os_error() == Some(26)
}

fn retry_etxtbsy<T, F>(mut op: F) -> io::Result<T>
where
    F: FnMut() -> io::Result<T>,
{
    let mut last_err: Option<io::Error> = None;
    for attempt in 0..ETXTBSY_ATTEMPTS {
        match op() {
            Ok(value) => return Ok(value),
            Err(err) if is_etxtbsy(&err) => {
                last_err = Some(err);
                if attempt + 1 < ETXTBSY_ATTEMPTS {
                    std::thread::sleep(Duration::from_millis(
                        50 * u64::from(attempt + 1),
                    ));
                }
            }
            Err(err) => return Err(err),
        }
    }
    Err(last_err.unwrap_or_else(|| io::Error::from_raw_os_error(26)))
}

fn copy_stub_once(src: &Path, tmp: &Path, dest: &Path) -> io::Result<()> {
    let _ = fs::remove_file(tmp);
    fs::copy(src, tmp)?;
    #[cfg(unix)]
    fsync_path(tmp)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(tmp)?.permissions();
        perms.set_mode(0o755);
        fs::set_permissions(tmp, perms)?;
    }
    let _ = fs::remove_file(dest);
    fs::rename(tmp, dest)?;
    #[cfg(unix)]
    fsync_path(dest)?;
    Ok(())
}

#[cfg(unix)]
fn fsync_path(path: &Path) -> io::Result<()> {
    fs::File::open(path)?.sync_all()
}

fn copy_stub_with_retry(src: &Path, dest: &Path) {
    let tmp = dest.with_extension("exe.part");
    retry_etxtbsy(|| copy_stub_once(src, &tmp, dest)).unwrap_or_else(|err| {
        panic!("copy stub to {}: {err}", dest.display());
    });
}

fn install_named_stub(dir: &Path, name: &str) -> PathBuf {
    let dest = dir.join(format!("{name}.exe"));
    copy_stub_with_retry(&stub_binary(), &dest);
    dest
}

fn run_stub(exe: &Path, args: &[&str]) -> std::process::Output {
    retry_etxtbsy(|| Command::new(exe).args(args).output()).unwrap_or_else(|err| {
        panic!("failed to run {}: {err}", exe.display());
    })
}

#[test]
fn copies_stdout_stderr_and_exit_from_sidecars() {
    let dir = make_temp_dir();
    let exe = install_named_stub(&dir, "ipconfig");
    fs::write(dir.join("ipconfig.stdout"), "flushed-ok\n").expect("stdout");
    fs::write(dir.join("ipconfig.stderr"), "warn\n").expect("stderr");
    fs::write(dir.join("ipconfig.exit"), "3\n").expect("exit");
    let log_path = dir.join("_calls").join("ipconfig.log");
    fs::create_dir_all(log_path.parent().expect("log parent")).expect("calls dir");
    fs::write(&log_path, "").expect("empty log");
    let output = run_stub(&exe, &["/flushdns"]);
    assert_eq!(output.status.code(), Some(3));
    assert_eq!(output.stdout, b"flushed-ok\n");
    assert_eq!(output.stderr, b"warn\n");
    let log = fs::read_to_string(dir.join("_calls").join("ipconfig.log")).expect("log");
    assert_eq!(log.lines().collect::<Vec<_>>(), [r#"["/flushdns"]"#]);
    remove_temp_dir(&dir);
}

#[test]
fn missing_sidecars_yield_empty_output_and_zero_exit() {
    let dir = make_temp_dir();
    let exe = install_named_stub(&dir, "timeout");
    let log_path = dir.join("_calls").join("timeout.log");
    fs::create_dir_all(log_path.parent().expect("log parent")).expect("calls dir");
    fs::write(&log_path, "").expect("empty log");
    let output = run_stub(&exe, &[]);
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stdout.is_empty());
    assert!(output.stderr.is_empty());
    let log = fs::read_to_string(dir.join("_calls").join("timeout.log")).expect("log");
    assert_eq!(log, "[]\n");
    remove_temp_dir(&dir);
}

#[test]
fn skips_call_log_when_log_file_is_absent() {
    let dir = make_temp_dir();
    let exe = install_named_stub(&dir, "net");
    fs::write(dir.join("net.exit"), "0").expect("exit");
    let output = run_stub(&exe, &["session"]);
    assert_eq!(output.status.code(), Some(0));
    assert!(!dir.join("_calls").join("net.log").exists());
    remove_temp_dir(&dir);
}

#[test]
fn returns_to_caller_across_multiple_invocations() {
    let dir = make_temp_dir();
    let exe = install_named_stub(&dir, "net");
    fs::write(dir.join("net.exit"), "0").expect("exit");
    let log_path = dir.join("_calls").join("net.log");
    fs::create_dir_all(log_path.parent().expect("log parent")).expect("calls dir");
    fs::write(&log_path, "").expect("empty log");
    let first = run_stub(&exe, &["session"]);
    let second = run_stub(&exe, &["user"]);
    assert_eq!(first.status.code(), Some(0));
    assert_eq!(second.status.code(), Some(0));
    let log = fs::read_to_string(dir.join("_calls").join("net.log")).expect("log");
    assert_eq!(
        log.lines().collect::<Vec<_>>(),
        [r#"["session"]"#, r#"["user"]"#]
    );
    remove_temp_dir(&dir);
}

#[test]
fn logs_multiple_arguments_on_one_line() {
    let dir = make_temp_dir();
    let exe = install_named_stub(&dir, "reg");
    fs::write(dir.join("reg.exit"), "1").expect("exit");
    let log_path = dir.join("_calls").join("reg.log");
    fs::create_dir_all(log_path.parent().expect("log parent")).expect("calls dir");
    fs::write(&log_path, "").expect("empty log");
    let output = run_stub(&exe, &["query", r"HKLM\Software", "/v", "Name"]);
    assert_eq!(output.status.code(), Some(1));
    let log = fs::read_to_string(dir.join("_calls").join("reg.log")).expect("log");
    assert_eq!(
        log.lines().collect::<Vec<_>>(),
        [r#"["query","HKLM\\Software","/v","Name"]"#]
    );
    remove_temp_dir(&dir);
}

#[test]
fn pipes_binary_stdout_without_utf8() {
    let dir = make_temp_dir();
    let exe = install_named_stub(&dir, "tool");
    fs::write(dir.join("tool.stdout"), [0xff, 0xfe, b'x']).expect("binary stdout");
    fs::write(dir.join("tool.exit"), "0").expect("exit");
    let output = run_stub(&exe, &["--raw"]);
    assert_eq!(output.stdout, [0xff, 0xfe, b'x']);
    remove_temp_dir(&dir);
}

#[test]
fn retries_etxtbsy_then_succeeds() {
    let mut attempts = 0;
    let result = retry_etxtbsy(|| {
        attempts += 1;
        if attempts < 3 {
            Err(io::Error::from_raw_os_error(26))
        } else {
            Ok(7)
        }
    });
    assert_eq!(result.expect("retry should succeed"), 7);
    assert_eq!(attempts, 3);
}

#[test]
fn etxtbsy_retry_propagates_other_errors_immediately() {
    let mut attempts = 0;
    let result: io::Result<()> = retry_etxtbsy(|| {
        attempts += 1;
        Err(io::Error::new(io::ErrorKind::NotFound, "missing"))
    });
    assert_eq!(attempts, 1);
    let err = result.expect_err("non-busy errors must not retry");
    assert_eq!(err.kind(), io::ErrorKind::NotFound);
}
