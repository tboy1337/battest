//! Integration tests that run the battest-stub binary like PATH mocks do.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_DIR_SEQ: AtomicU64 = AtomicU64::new(0);

fn make_temp_dir() -> PathBuf {
    let seq = TEST_DIR_SEQ.fetch_add(1, Ordering::Relaxed);
    let path =
        env::temp_dir().join(format!("battest-stub-cli-{}-{seq}", std::process::id()));
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

fn install_named_stub(dir: &Path, name: &str) -> PathBuf {
    let dest = dir.join(format!("{name}.exe"));
    fs::copy(stub_binary(), &dest).expect("copy stub");
    dest
}

fn run_stub(exe: &Path, args: &[&str]) -> std::process::Output {
    Command::new(exe)
        .args(args)
        .output()
        .unwrap_or_else(|err| panic!("failed to run {}: {err}", exe.display()))
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
