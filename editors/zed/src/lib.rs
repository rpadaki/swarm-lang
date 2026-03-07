use zed_extension_api::{self as zed, settings::LspSettings, Result};

struct SwarmExtension;

impl zed::Extension for SwarmExtension {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        _language_server_id: &zed::LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<zed::Command> {
        let binary_settings = LspSettings::for_worktree("swarm-lsp", worktree)
            .ok()
            .and_then(|s| s.binary);

        if let Some(ref settings) = binary_settings {
            if let Some(ref path) = settings.path {
                return Ok(zed::Command {
                    command: path.clone(),
                    args: settings.arguments.clone().unwrap_or_default(),
                    env: Default::default(),
                });
            }
        }

        let uv = worktree.which("uv").ok_or("uv not found in PATH")?;
        let root = worktree.root_path();
        Ok(zed::Command {
            command: uv,
            args: vec![
                "run".into(),
                "--project".into(),
                root.clone(),
                "python".into(),
                "-m".into(),
                "swarm".into(),
                "lsp".into(),
            ],
            env: Default::default(),
        })
    }
}

zed::register_extension!(SwarmExtension);
