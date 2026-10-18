use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

const HOST: &str = "127.0.0.1";
const PORT: u16 = 8765;

struct BackendProcess(Mutex<Option<CommandChild>>);

fn port_open() -> bool {
    let address: SocketAddr = format!("{HOST}:{PORT}").parse().expect("valid address");
    TcpStream::connect_timeout(&address, Duration::from_millis(220)).is_ok()
}

fn find_repo_root() -> Option<PathBuf> {
    let mut current = std::env::current_exe().ok()?;
    for _ in 0..10 {
        current = current.parent()?.to_path_buf();
        if current
            .join("services")
            .join("api")
            .join("aibox_api")
            .is_dir()
        {
            return Some(current);
        }
    }
    None
}

fn venv_python(repo: &Path) -> PathBuf {
    if let Ok(explicit) = std::env::var("AIBOX_PYTHON") {
        return PathBuf::from(explicit);
    }
    if cfg!(target_os = "windows") {
        repo.join(".venv").join("Scripts").join("python.exe")
    } else {
        repo.join(".venv").join("bin").join("python")
    }
}

fn start_backend(app: &tauri::AppHandle) -> Option<CommandChild> {
    if port_open() {
        return None;
    }

    let shell = app.shell();
    let command = if cfg!(debug_assertions) {
        let repo = find_repo_root()?;
        let python = venv_python(&repo);
        if !python.is_file() {
            eprintln!(
                "[AIBox] Python environment not found at {}. Run the setup script first.",
                python.display()
            );
            return None;
        }
        shell
            .command(python.to_string_lossy().to_string())
            .current_dir(repo)
            .args([
                "-m",
                "aibox_api",
                "--host",
                HOST,
                "--port",
                &PORT.to_string(),
            ])
    } else {
        match shell.sidecar("aibox-server") {
            Ok(command) => command.args([
                "--host",
                HOST,
                "--port",
                &PORT.to_string(),
            ]),
            Err(error) => {
                eprintln!("[AIBox] Unable to locate the bundled API sidecar: {error}");
                return None;
            }
        }
    };

    match command.spawn() {
        Ok((mut events, child)) => {
            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    if let tauri_plugin_shell::process::CommandEvent::Stderr(line) = event {
                        let text = String::from_utf8_lossy(&line);
                        eprintln!("[AIBox API] {}", text.trim_end());
                    }
                }
            });
            Some(child)
        }
        Err(error) => {
            eprintln!("[AIBox] Failed to start the local API: {error}");
            None
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let backend = start_backend(&app.handle());
            app.manage(BackendProcess(Mutex::new(backend)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the AIBox desktop window");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            if let Some(state) = app_handle.try_state::<BackendProcess>() {
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(child) = guard.take() {
                        let _ = child.kill();
                    }
                }
            }
        }
    });
}
