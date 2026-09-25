//! TunaOS installer — a real COSMIC application.
//!
//! This was previously plain `iced` with `.theme(|_| Theme::Dark)` hardcoded.
//! That is why it never looked like a COSMIC app: `libcosmic` was not a
//! dependency at all, so none of the COSMIC design system was linked in. It
//! also did not compile — the source was written against the iced 0.13 API
//! while `Cargo.toml` asked for 0.14, and nothing in CI ever built it.
//!
//! It is now a `cosmic::Application`: COSMIC header bar, `cosmic-theme`
//! palette and spacing, and the cosmic widget set.

mod capture;
mod model;
mod readiness;
mod offline;
mod progress;
mod branding;
mod ui;

use cosmic::app::{Core, Settings, Task};
use cosmic::iced::{Length, Size};
use cosmic::prelude::*;
use cosmic::widget;
use cosmic::iced::futures::{SinkExt, Stream, StreamExt};
use std::process::Command as SysCommand;
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command as TokioCommand;

pub use model::{DiskInfo, Recipe, FILESYSTEMS};

pub const APP_ID: &str = "org.tunaos.InstallerCosmic";

fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();

    let flags = Flags {
        capture: capture::Capture::from_env(),
    };

    let mut settings = Settings::default()
        // COSMIC ships its own icon theme, but the installer also runs on live
        // media that may only have Adwaita. freedesktop-icons falls back
        // through the theme's inherit chain, so naming Adwaita here means the
        // icons resolve in both places instead of silently drawing nothing —
        // which is exactly what the first screenshot run caught.
        .default_icon_theme("Adwaita")
        .size(Size::new(1000.0, 700.0))
        .size_limits(
            cosmic::iced::Limits::NONE
                .min_width(600.0)
                .min_height(480.0),
        );

    // Deterministic captures: the system preference is whatever the CI runner
    // happens to have, which would make the screenshots flap between light and
    // dark. Pin the theme when capturing, follow the user otherwise.
    if flags.capture.is_some() {
        settings = settings.theme(cosmic::theme::Theme::dark());
    }

    cosmic::app::run::<TunaInstaller>(settings, flags)?;
    Ok(())
}

pub struct Flags {
    pub capture: Option<capture::Capture>,
}

// ---------------------------------------------------------------- pages ----

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Page {
    Welcome,
    DiskSelect,
    Options,
    Confirm,
    Installing,
    Done,
}

impl Page {
    /// Wizard order. Also the capture order, so a new page cannot be added
    /// without appearing in the walkthrough.
    pub const ORDER: [Page; 6] = [
        Page::Welcome,
        Page::DiskSelect,
        Page::Options,
        Page::Confirm,
        Page::Installing,
        Page::Done,
    ];

    pub const fn slug(self) -> &'static str {
        match self {
            Page::Welcome => "welcome",
            Page::DiskSelect => "disk",
            Page::Options => "options",
            Page::Confirm => "confirm",
            Page::Installing => "installing",
            Page::Done => "done",
        }
    }

    pub const fn title(self) -> &'static str {
        match self {
            Page::Welcome => "Welcome",
            Page::DiskSelect => "Select a disk",
            Page::Options => "Options",
            Page::Confirm => "Confirm",
            Page::Installing => "Installing",
            Page::Done => "Finished",
        }
    }

    fn index(self) -> usize {
        Page::ORDER.iter().position(|p| *p == self).unwrap_or(0)
    }
}

/// One entry in the encryption picker.
///
/// `id` is what actually lands in `recipe.encryption.type` and it MUST be one
/// of the four values `fisherman` accepts (`fisherman/internal/recipe/recipe.go`
/// `Validate()`): "none", "luks-passphrase", "tpm2-luks",
/// "tpm2-luks-passphrase". Anything else — the previous `"luks"` here — fails
/// recipe validation and the install never starts, which is a worse failure
/// mode than never offering encryption at all: the user thinks they chose it.
#[derive(Debug, Clone, Copy)]
pub struct EncryptionChoice {
    pub id: &'static str,
    pub label: &'static str,
    pub description: &'static str,
    /// Only offered when a TPM2 chip is present (tunaOS#734 / tuna-installer-xfce
    /// `ENCRYPTION_CHOICES`, which this mirrors value-for-value so a recipe
    /// produced by either frontend means the same thing).
    pub tpm: bool,
}

// `static`, not `const`: `available_encryption_choices` hands out
// `&'static EncryptionChoice`s borrowed straight from this table. A `const`
// has no fixed address (each use site may get its own inlined copy), so
// relying on it for a genuinely `'static` borrow depends on rvalue-static-
// promotion kicking in. `static` sidesteps the question — it has exactly one
// address for the life of the program, so the borrow is `'static` outright.
pub static ENCRYPTION_CHOICES: [EncryptionChoice; 4] = [
    EncryptionChoice {
        id: "none",
        label: "No encryption",
        description: "Anyone with the disk can read your files.",
        tpm: false,
    },
    EncryptionChoice {
        id: "luks-passphrase",
        label: "Passphrase",
        description: "You'll type it at every boot.",
        tpm: false,
    },
    EncryptionChoice {
        id: "tpm2-luks",
        label: "TPM",
        description: "Unlocks automatically on this hardware.",
        tpm: true,
    },
    EncryptionChoice {
        id: "tpm2-luks-passphrase",
        label: "TPM + passphrase",
        description: "Automatic unlock, passphrase as fallback.",
        tpm: true,
    },
];

/// The choices actually selectable right now. TPM-gated entries are dropped
/// entirely rather than shown-disabled when there is no TPM — same call
/// `tuna-installer-xfce` makes (`SetupPage.__init__`: `if value.startswith("tpm2")
/// and not self.has_tpm: continue`), and for the same reason: a dropdown entry
/// that silently produces an unenrollable recipe is worse than one that isn't
/// offered.
/// Whether the TPM encryption choices should be offered.
///
/// `BOOTC_INSTALLER_FAKE_TPM` only ever forces this ON, and exists so a
/// capture can show what the installer offers rather than what the runner's
/// hardware allows. Empty and "0" do not count as set, so an exported but
/// blank variable cannot silently turn the choices on everywhere.
pub fn tpm_available() -> bool {
    match std::env::var("BOOTC_INSTALLER_FAKE_TPM") {
        Ok(v) if !v.is_empty() && v != "0" => true,
        _ => probe_tpm2(std::path::Path::new("/")),
    }
}

/// The kernel writes the TCG spec major version here: "2" for TPM 2.0, "1"
/// for TPM 1.2. Added in Linux 5.5.
const TPM_VERSION_FILE: &str = "sys/class/tpm/tpm0/tpm_version_major";

/// The in-kernel resource manager is a TPM 2.0 feature, so the kernel makes
/// this node only for a 2.0 device. Fallback for kernels older than 5.5.
const TPM_RESOURCE_MANAGER: &str = "dev/tpmrm0";

/// Whether `root` holds a TPM 2.0 device, per shared/tpm/README.md.
///
/// This used to test `/sys/class/tpm/tpm0` for existence, which the kernel
/// also creates for a TPM 1.2 device -- so a 1.2 machine was offered
/// tpm2-luks and the install failed at enrolment, after the disk had been
/// partitioned. The `root` parameter is what makes this testable: no CI
/// runner has a TPM of any version, so the tests point it at a fixture tree.
pub fn probe_tpm2(root: &std::path::Path) -> bool {
    match std::fs::read_to_string(root.join(TPM_VERSION_FILE)) {
        Ok(v) => v.trim() == "2",
        Err(_) => root.join(TPM_RESOURCE_MANAGER).exists(),
    }
}

pub fn available_encryption_choices(has_tpm: bool) -> Vec<&'static EncryptionChoice> {
    ENCRYPTION_CHOICES
        .iter()
        .filter(|c| !c.tpm || has_tpm)
        .collect()
}

// -------------------------------------------------------------- messages ----

#[derive(Debug, Clone)]
pub enum Message {
    NextPage,
    BackPage,
    SelectDisk(usize),
    DisksScanned(Result<Vec<DiskInfo>, String>),
    /// Resolved asynchronously so init() never blocks on a host command.
    LiveImageResolved(Option<String>),
    HostnameChanged(String),
    FilesystemChanged(usize),
    EncryptionChanged(usize),
    PassphraseChanged(String),
    TogglePassphraseVisible,
    /// The done page's "I have saved my recovery key" box.
    RecoveryAckToggled(bool),
    /// Put the recovery key on the clipboard.
    CopyRecoveryKey,
    StartInstall,
    /// One line of fisherman's stdout, as it arrives.
    ///
    /// run_fisherman() used to be `.output()`: it waited for the process to
    /// exit and handed back everything at once, so the log appeared only when
    /// the install was already over and any progress bar fed from it would
    /// have jumped from nothing to done. Parsing alone would not have given
    /// this frontend a working bar; it needed the output to arrive while the
    /// install is running.
    InstallLine(String),
    InstallFinished(Result<i32, String>),
    Quit,
    /// The done page's Restart: `systemctl reboot` on the host.
    Reboot,
    /// The done page's store link.
    OpenUrl(String),
    /// Capture harness only — never reachable from the UI.
    Capture(capture::Message),
}

pub struct TunaInstaller {
    core: Core,
    page: Page,
    live_image: Option<String>,
    recipe: Recipe,
    disks: Vec<DiskInfo>,
    selected_disk: Option<usize>,
    install_log: String,
    /// The install's position, parsed from fisherman's protocol
    /// (shared/progress/README.md). Before this the install page showed an
    /// indeterminate bar for the whole install — docs/PARITY.md gap #2.
    progress: progress::Progress,
    install_ok: bool,
    installing: bool,
    passphrase_hidden: bool,
    /// Ticked by the user on the done page once they have written the
    /// recovery key down. It gates Restart (#129).
    recovery_ack: bool,
    /// `/sys/class/tpm/tpm0` existence, checked once at startup — same probe
    /// `tuna-installer-xfce` uses. Gates the two `tpm2-*` encryption choices.
    has_tpm: bool,
    /// `Some` only in capture mode. Its presence is also the hard interlock
    /// that stops the capture harness ever running a real install.
    capture: Option<capture::Capture>,
}

impl TunaInstaller {
    pub fn page(&self) -> Page {
        self.page
    }

    /// True while a recovery key is on screen that the user has not yet
    /// acknowledged (#129). The done page holds Restart until this clears:
    /// leaving that page is what ends the chance to read the key.
    ///
    /// A failed install enrolled nothing, so there is no key to hold for.
    pub fn recovery_key_pending(&self) -> bool {
        progress::holds_restart(
            self.install_ok,
            &self.progress.recovery_key,
            self.recovery_ack,
        )
    }

    pub fn recipe(&self) -> &Recipe {
        &self.recipe
    }
    pub fn disks(&self) -> &[DiskInfo] {
        &self.disks
    }
    pub fn selected_disk(&self) -> Option<usize> {
        self.selected_disk
    }
    pub fn live_image(&self) -> Option<&str> {
        self.live_image.as_deref()
    }
    pub fn install_log(&self) -> &str {
        &self.install_log
    }

    pub fn progress(&self) -> &progress::Progress {
        &self.progress
    }
    pub fn install_ok(&self) -> bool {
        self.install_ok
    }
    pub fn installing(&self) -> bool {
        self.installing
    }
    pub fn passphrase_hidden(&self) -> bool {
        self.passphrase_hidden
    }
    pub fn capturing(&self) -> bool {
        self.capture.is_some()
    }
    pub fn has_tpm(&self) -> bool {
        self.has_tpm
    }

    /// Whether the Options page is allowed to advance. The dropdown can only
    /// ever hold a valid `enc_type` (see `Message::EncryptionChanged`), so the
    /// one thing left to check is the passphrase fisherman's own `Validate()`
    /// requires for "luks-passphrase" and "tpm2-luks-passphrase": both contain
    /// the substring "passphrase", matching `tuna-installer-xfce`'s
    /// `"passphrase" in enc_type()` check. Without this gate, a user who left
    /// the field blank would sail through Confirm and only discover the
    /// problem when fisherman rejects the recipe on the Installing page.
    pub fn encryption_ok(&self) -> bool {
        if self.recipe.encryption.enc_type.contains("passphrase") {
            !self.recipe.encryption.passphrase.is_empty()
        } else {
            true
        }
    }

    fn advance(&mut self) -> Option<Page> {
        let next = match self.page {
            Page::Welcome => Page::DiskSelect,
            Page::DiskSelect => Page::Options,
            Page::Options => Page::Confirm,
            Page::Confirm | Page::Installing | Page::Done => return None,
        };
        self.page = next;
        Some(next)
    }

    fn retreat(&mut self) {
        self.page = match self.page {
            Page::Confirm => Page::Options,
            Page::Options => Page::DiskSelect,
            Page::DiskSelect => Page::Welcome,
            other => other,
        };
    }
}

impl cosmic::Application for TunaInstaller {
    type Executor = cosmic::executor::Default;
    type Flags = Flags;
    type Message = Message;

    const APP_ID: &'static str = APP_ID;

    fn core(&self) -> &Core {
        &self.core
    }

    fn core_mut(&mut self) -> &mut Core {
        &mut self.core
    }

    fn init(core: Core, flags: Flags) -> (Self, Task<Message>) {
        let capturing = flags.capture.is_some();

        // Recipe::default() is neutral; the product identity comes from the
        // branding contract (shared/branding/README.md). The default image
        // is what a non-live install writes when nothing else chooses one;
        // live-ISO mode clears it below.
        let mut recipe = Recipe::default();
        {
            let b = branding::get();
            recipe.distro_id = b.id.clone();
            recipe.hostname = b.default_hostname.clone();
            recipe.image = b.default_image.clone();
        }
        let mut disks = Vec::new();
        let live;
        let mut init_tasks: Vec<Task<Message>> = Vec::new();

        if capturing {
            // Fixtures. In capture mode nothing shells out: no `bootc status`,
            // no `lsblk`, no `podman`. The machine in the screenshots does not
            // exist, so the output is deterministic and CI never sees a disk.
            disks = capture::fixture_disks();
            live = Some(capture::FIXTURE_LIVE_IMAGE.to_string());
            recipe.image = String::new();
        } else {
            // Offline install support (spec §4): live-ISO mode installs the
            // running container (empty image); embedded stores are always
            // passed.
            //
            // `live_iso_image` shells out to the host via flatpak-spawn and
            // MUST NOT block init(). Iced creates the window *after* init
            // returns, so a hung host command would leave the process alive
            // with no window — exactly the failure mode tunaOS#678 caught.
            // Defer it to an async task and start with `live_image = None`;
            // the Confirm page handles `None` gracefully (it just shows the
            // default image ref).
            init_tasks.push(Task::perform(
                tokio::task::spawn_blocking(offline::live_iso_image),
                |r| cosmic::action::app(Message::LiveImageResolved(r.unwrap_or(None))),
            ));
            recipe.additional_image_stores = offline::offline_stores();
            live = None;
        }

        if let Some(first) = disks.first() {
            recipe.disk = format!("/dev/{}", first.name);
        }

        // Same probe as the XFCE frontend's `core.has_tpm()` and KDE's
        // InstallerController, and the same override for the same reason.
        //
        // The Xvfb CI runner has no TPM, so an unset capture renders an
        // encryption page with only two of the four choices. docs/PARITY.md is
        // read off those screenshots, which is how KDE and XFCE came to be
        // recorded as having no TPM support at all when both have offered it
        // all along. BOOTC_INSTALLER_FAKE_TPM=1 makes the choices VISIBLE for
        // captures only; picking one still writes an ordinary recipe, and
        // fisherman is what fails, later and loudly, with no chip to enrol
        // against.
        let has_tpm = tpm_available();

        let mut app = Self {
            core,
            page: Page::Welcome,
            live_image: live,
            recipe,
            selected_disk: (!disks.is_empty()).then_some(0),
            disks,
            install_log: String::new(),
            progress: progress::Progress::new(branding::name()),
            install_ok: false,
            installing: false,
            passphrase_hidden: true,
            recovery_ack: false,
            has_tpm,
            capture: flags.capture,
        };

        // The product name from the branding contract (branding.json, then
        // os-release), never a literal — see `branding`.
        let window_title = format!("{} Installer", branding::name());
        let mut tasks = vec![app.set_window_title(window_title.clone())];
        tasks.append(&mut init_tasks);
        if app.capture.is_some() {
            tasks.push(capture::begin());
        } else {
            tasks.push(Task::perform(Self::scan_disks(), |r| {
                cosmic::action::app(Message::DisksScanned(r))
            }));
        }
        app.set_header_title(window_title);

        (app, Task::batch(tasks))
    }

    fn header_start(&self) -> Vec<Element<'_, Message>> {
        // The step indicator lives in the COSMIC header bar rather than being
        // drawn by hand in the page body, which is what makes this read as a
        // COSMIC app instead of a generic iced window.
        let spacing = cosmic::theme::active().cosmic().spacing;
        vec![widget::text::caption(format!(
            "Step {} of {} · {}",
            self.page.index() + 1,
            Page::ORDER.len(),
            self.page.title()
        ))
        .apply(widget::container)
        .padding([0, spacing.space_xs])
        .into()]
    }

    fn header_end(&self) -> Vec<Element<'_, Message>> {
        vec![widget::progress_bar::determinate_linear(
            (self.page.index() as f32 + 1.0) / Page::ORDER.len() as f32,
        )
        .width(Length::Fixed(120.0))
        .into()]
    }

    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::NextPage => {
                if let Some(Page::DiskSelect) = self.advance() {
                    if !self.capturing() {
                        return Task::perform(Self::scan_disks(), |r| {
                            cosmic::action::app(Message::DisksScanned(r))
                        });
                    }
                }
                Task::none()
            }
            Message::BackPage => {
                self.retreat();
                Task::none()
            }
            Message::SelectDisk(idx) => {
                if let Some(disk) = self.disks.get(idx) {
                    self.selected_disk = Some(idx);
                    self.recipe.disk = format!("/dev/{}", disk.name);
                }
                Task::none()
            }
            Message::DisksScanned(Ok(disks)) => {
                self.disks = disks;
                if !self.disks.is_empty() && self.selected_disk.is_none() {
                    self.selected_disk = Some(0);
                    self.recipe.disk = format!("/dev/{}", self.disks[0].name);
                }
                Task::none()
            }
            Message::DisksScanned(Err(err)) => {
                self.install_log
                    .push_str(&format!("Disk scan error: {err}\n"));
                Task::none()
            }
            Message::LiveImageResolved(live) => {
                self.live_image = live;
                if self.live_image.is_some() {
                    self.recipe.image = String::new();
                }
                Task::none()
            }
            Message::HostnameChanged(h) => {
                self.recipe.hostname = h;
                Task::none()
            }
            Message::FilesystemChanged(idx) => {
                if let Some(fs) = FILESYSTEMS.get(idx) {
                    self.recipe.filesystem = (*fs).to_string();
                    self.recipe.btrfs_subvolumes = *fs == "btrfs";
                }
                Task::none()
            }
            Message::EncryptionChanged(idx) => {
                // Recompute the same has_tpm-filtered list ui.rs built the
                // dropdown from, so `idx` (a position in THAT list) resolves
                // to the same choice the user actually saw and clicked.
                let choices = available_encryption_choices(self.has_tpm);
                if let Some(choice) = choices.get(idx) {
                    self.recipe.encryption.enc_type = choice.id.to_string();
                    // Only "luks-passphrase" and "tpm2-luks-passphrase" carry a
                    // passphrase; clear it for "none" and bare "tpm2-luks" so a
                    // stale value from a previous choice can't linger into the
                    // recipe (fisherman ignores it, but Confirm would still
                    // display it — see `.contains("passphrase")` above).
                    if !choice.id.contains("passphrase") {
                        self.recipe.encryption.passphrase.clear();
                    }
                }
                Task::none()
            }
            Message::PassphraseChanged(p) => {
                self.recipe.encryption.passphrase = p;
                Task::none()
            }
            Message::TogglePassphraseVisible => {
                self.passphrase_hidden = !self.passphrase_hidden;
                Task::none()
            }
            Message::RecoveryAckToggled(v) => {
                self.recovery_ack = v;
                Task::none()
            }
            Message::CopyRecoveryKey => {
                cosmic::iced::clipboard::write(self.progress.recovery_key.clone())
            }
            Message::StartInstall => {
                // SAFETY INTERLOCK. Driving the wizard to the progress page
                // must never partition the CI runner's disk. A sibling repo
                // (tuna-installer-xfce) called start_install() from the
                // page-enter hook, so a naive capture would have done exactly
                // that. Here the capture harness sets `page` directly and
                // never emits StartInstall — and if it ever did, this refuses.
                if self.capturing() {
                    tracing::error!("StartInstall ignored: capture mode");
                    return Task::none();
                }
                self.page = Page::Installing;
                self.installing = true;
                self.progress.reset();
                let recipe = self.recipe.clone();
                Task::stream(Self::stream_fisherman(recipe).map(cosmic::action::app))
            }
            Message::InstallLine(line) => {
                // Through the same parser the capture harness drives, so the
                // bar on the screenshot is the bar a real install shows.
                if let Some(shown) = self.progress.consume(&line) {
                    self.install_log.push_str(&shown);
                    self.install_log.push('\n');
                }
                Task::none()
            }
            Message::InstallFinished(result) => {
                self.page = Page::Done;
                self.installing = false;
                match result {
                    Ok(code) => {
                        self.install_ok = code == 0;
                        self.install_log
                            .push_str(&format!("\n=== fisherman exited with code {code} ===\n"));
                    }
                    Err(e) => {
                        self.install_ok = false;
                        self.install_log.push_str(&format!("\n=== Error: {e} ===\n"));
                    }
                }
                offline::persist_install_log(&self.install_log);
                Task::none()
            }
            Message::Quit => {
                std::process::exit(i32::from(!self.install_ok));
            }
            Message::OpenUrl(url) => {
                let argv = offline::host_command(&["xdg-open", &url]);
                if let Some((program, args)) = argv.split_first() {
                    let _ = std::process::Command::new(program).args(args).spawn();
                }
                Task::none()
            }
            Message::Reboot => {
                let argv = offline::host_command(&["systemctl", "reboot"]);
                if let Some((program, args)) = argv.split_first() {
                    let _ = std::process::Command::new(program).args(args).spawn();
                }
                Task::none()
            }
            Message::Capture(msg) => capture::update(self, msg),
        }
    }

    fn view(&self) -> Element<'_, Message> {
        // First frame = the strongest honest "the UI came up" signal libcosmic
        // offers. See readiness.rs: this frontend is the one that proved
        // `flatpak ps` insufficient, by running with no window ever appearing
        // while the smoke check stayed green. Cheap after the first call.
        readiness::stamp_first_frame(APP_ID, self.page.slug());
        ui::view(self)
    }
}

// -------------------------------------------------------- async helpers ----

impl TunaInstaller {
    async fn scan_disks() -> Result<Vec<DiskInfo>, String> {
        let output = tokio::task::spawn_blocking(|| {
            SysCommand::new("lsblk")
                .args(["-J", "-o", "NAME,SIZE,TYPE,MODEL,TRAN"])
                .output()
                .map_err(|e| format!("Failed to run lsblk: {e}"))
        })
        .await
        .map_err(|e| format!("Task join error: {e}"))??;

        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).into_owned());
        }

        let val: serde_json::Value = serde_json::from_slice(&output.stdout)
            .map_err(|e| format!("Failed to parse lsblk JSON: {e}"))?;

        let mut disks = Vec::new();
        if let Some(devices) = val.get("blockdevices").and_then(|d| d.as_array()) {
            for dev in devices {
                if dev.get("type").and_then(|t| t.as_str()) == Some("disk") {
                    let field = |k: &str| {
                        dev.get(k)
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string()
                    };
                    disks.push(DiskInfo {
                        name: field("name"),
                        size: field("size"),
                        model: field("model"),
                        transport: field("tran"),
                    });
                }
            }
        }
        Ok(disks)
    }

    /// Runs fisherman and yields its output a line at a time, then the exit
    /// code.
    ///
    /// This was `.output()`, which waits for the process to exit and returns
    /// everything at once. That was already a problem for the log — the Done
    /// page tells the user "the install log above has the details" and the
    /// log only existed once there was nothing left to watch — and it makes a
    /// progress bar impossible on its own terms: every event would arrive
    /// after the install had finished. Parsing fisherman's protocol was
    /// necessary for a working bar here but not sufficient; the output has to
    /// arrive while the install is running.
    ///
    /// stdout carries the newline-delimited JSON protocol
    /// (shared/progress/README.md); stderr is plain text and is interleaved
    /// into the same stream, which the parser passes through untouched.
    fn stream_fisherman(recipe: Recipe) -> impl Stream<Item = Message> {
        cosmic::iced::stream::channel(64, async move |mut output| {
            let json = match serde_json::to_string_pretty(&recipe) {
                Ok(json) => json,
                Err(e) => {
                    let _ = output.send(Message::InstallFinished(Err(e.to_string()))).await;
                    return;
                }
            };
            // 0600 under XDG_RUNTIME_DIR — the recipe may hold a passphrase.
            let path = match offline::write_recipe(&json) {
                Ok(path) => path,
                Err(e) => {
                    let _ = output.send(Message::InstallFinished(Err(e.to_string()))).await;
                    return;
                }
            };

            // pkexec /app/bin/fisherman in Flatpak, sudo otherwise.
            let cmd = offline::fisherman_command();
            let mut child = match TokioCommand::new(&cmd[0])
                .args(&cmd[1..])
                .arg(&path)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
            {
                Ok(child) => child,
                Err(e) => {
                    let _ = std::fs::remove_file(&path);
                    let _ = output
                        .send(Message::InstallFinished(Err(format!(
                            "Failed to run fisherman: {e}"
                        ))))
                        .await;
                    return;
                }
            };

            let stdout = child.stdout.take();
            let stderr = child.stderr.take();
            if let Some(stdout) = stdout {
                let mut lines = BufReader::new(stdout).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    if output.send(Message::InstallLine(line)).await.is_err() {
                        break;
                    }
                }
            }
            // Drained after stdout: fisherman writes its failure summary
            // there, and dropping it is how a failed install used to reach
            // the Done page with nothing to show.
            if let Some(stderr) = stderr {
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    if output.send(Message::InstallLine(line)).await.is_err() {
                        break;
                    }
                }
            }

            let code = match child.wait().await {
                Ok(status) => status.code().unwrap_or(-1),
                Err(e) => {
                    let _ = std::fs::remove_file(&path);
                    let _ = output.send(Message::InstallFinished(Err(e.to_string()))).await;
                    return;
                }
            };
            let _ = std::fs::remove_file(&path);
            if code != 0 {
                tracing::error!("fisherman exited with code {code}");
            }
            let _ = output.send(Message::InstallFinished(Ok(code))).await;
        })
    }
}

#[cfg(test)]
mod tests {
    // The capture override. Without it the Xvfb runner's missing TPM decides
    // what the screenshots show, and docs/PARITY.md is read off those.
    // Serialised with a mutex: these mutate process-wide environment, and
    // cargo runs tests in threads.
    #[test]
    fn tpm_available_honours_the_capture_override() {
        use std::sync::Mutex;
        static ENV_LOCK: Mutex<()> = Mutex::new(());
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());

        let real = std::path::Path::new("/sys/class/tpm/tpm0").exists();

        unsafe { std::env::remove_var("BOOTC_INSTALLER_FAKE_TPM") };
        assert_eq!(super::tpm_available(), real, "unset must fall through to the probe");

        unsafe { std::env::set_var("BOOTC_INSTALLER_FAKE_TPM", "1") };
        assert!(super::tpm_available(), "the override must force it on");

        // Empty and "0" must not count as set.
        for value in ["", "0"] {
            unsafe { std::env::set_var("BOOTC_INSTALLER_FAKE_TPM", value) };
            assert_eq!(
                super::tpm_available(), real,
                "{value:?} must not force the choices on"
            );
        }

        unsafe { std::env::remove_var("BOOTC_INSTALLER_FAKE_TPM") };
    }

    #[test]
    fn override_makes_all_four_choices_available() {
        use std::sync::Mutex;
        static ENV_LOCK: Mutex<()> = Mutex::new(());
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());

        assert_eq!(super::available_encryption_choices(false).len(), 2);
        assert_eq!(super::available_encryption_choices(true).len(), 4);
    }

    use super::*;

    #[test]
    fn recipe_default_values_and_json_serialization() {
        let recipe = Recipe::default();
        assert_eq!(recipe.filesystem, "xfs");
        assert_eq!(recipe.encryption.enc_type, "none");
        // Neutral until the branding contract fills them in at init().
        assert_eq!(recipe.distro_id, "linux");
        assert_eq!(recipe.hostname, "linux");
        assert!(recipe.image.is_empty());
        assert!(recipe.selinux_disabled);

        let json_str = serde_json::to_string(&recipe).unwrap();
        let json: serde_json::Value = serde_json::from_str(&json_str).unwrap();

        assert_eq!(json["filesystem"], "xfs");
        assert_eq!(json["encryption"]["type"], "none");
        assert_eq!(json["distroID"], "linux");
        assert_eq!(json["hostname"], "linux");
        assert_eq!(json["selinuxDisabled"], true);
        assert!(json.get("image").is_none());
        assert!(json.get("targetImgref").is_none());
        assert!(json.get("bootloader").is_none());
    }

    /// shared/tpm/fixtures/ -- the same trees every frontend's probe is
    /// pointed at, so all five agree. See shared/tpm/README.md.
    fn tpm_fixture(tree: &str) -> std::path::PathBuf {
        std::path::Path::new("../../shared/tpm/fixtures").join(tree)
    }

    #[test]
    fn probe_tpm2_reads_the_version_rather_than_the_directory() {
        for (tree, want, why) in [
            ("tpm2", true, "tpm_version_major reads 2"),
            ("tpm12", false, "a TPM 1.2 device cannot do tpm2-luks"),
            ("legacy-tpm2", true, "no version file, but /dev/tpmrm0 is TPM2-only"),
            ("legacy-none", false, "no version file and no resource manager"),
        ] {
            assert_eq!(probe_tpm2(&tpm_fixture(tree)), want, "{tree}: {why}");
        }
    }

    #[test]
    fn encryption_choices_filtering() {
        let without_tpm = available_encryption_choices(false);
        assert_eq!(without_tpm.len(), 2);
        assert!(without_tpm.iter().all(|c| !c.tpm));
        assert_eq!(without_tpm[0].id, "none");
        assert_eq!(without_tpm[1].id, "luks-passphrase");

        let with_tpm = available_encryption_choices(true);
        assert_eq!(with_tpm.len(), 4);
        assert_eq!(with_tpm[2].id, "tpm2-luks");
        assert_eq!(with_tpm[3].id, "tpm2-luks-passphrase");
    }

    /// End to end: the Install button's code path against the real backend.
    ///
    /// `run_fisherman` is what `Message::StartInstall` performs: it writes
    /// the 0600 recipe, runs `fisherman_command()` (sudo
    /// /usr/local/bin/fisherman outside Flatpak), collects the output and
    /// persists the log. In the end-to-end job shared/e2e/setup.sh has put
    /// the validating shim at that path, so this exercises the real
    /// fisherman's Validate() on the recipe this crate serialises. Ignored
    /// by default: it needs TUNA_E2E_DISK and the shim.
    ///
    ///     TUNA_E2E_DISK=/dev/loopN cargo test --release -- --ignored e2e
    #[test]
    #[ignore]
    fn e2e_install_path_reaches_fisherman() {
        let disk = std::env::var("TUNA_E2E_DISK").expect("TUNA_E2E_DISK (run shared/e2e/setup.sh)");
        let mut recipe = Recipe::default();
        recipe.disk = disk;
        recipe.filesystem = "xfs".into();
        recipe.image = "quay.io/centos-bootc/centos-bootc:c10s".into();
        recipe.hostname = "cosmic-e2e".into();

        // Drive the real stream and feed it through the real parser, which
        // is what the install page does. The old form called run_fisherman()
        // and matched a string in its returned log; that function no longer
        // exists, because collecting the output after the process exits is
        // precisely what stopped this frontend having a progress bar.
        let rt = tokio::runtime::Runtime::new().unwrap();
        let (code, log, fraction) = rt.block_on(async {
            use cosmic::iced::futures::StreamExt;
            let mut stream = Box::pin(TunaInstaller::stream_fisherman(recipe));
            let mut progress = super::progress::Progress::new("ExampleOS");
            let mut log = String::new();
            let mut code = None;
            while let Some(message) = stream.next().await {
                match message {
                    Message::InstallLine(line) => {
                        if let Some(shown) = progress.consume(&line) {
                            log.push_str(&shown);
                            log.push('\n');
                        }
                    }
                    Message::InstallFinished(result) => {
                        code = Some(result.expect("fisherman could not be launched"));
                    }
                    _ => {}
                }
            }
            (code.expect("the stream ended without a result"), log, progress.fraction)
        });
        println!("{log}");
        assert_eq!(code, 0, "fisherman exit code");
        // Where the bar ended up, which is the property that was broken and
        // the one no string match could see: a frontend that does not parse
        // fisherman's protocol still reaches the Done page and still reports
        // success, and only the bar shows the difference.
        assert_eq!(
            fraction, 1.0,
            "the progress bar ended at {fraction}, not 1.0 — the install page              is not parsing fisherman's progress protocol              (shared/progress/README.md)"
        );
        assert!(
            log.contains("Installation complete"),
            "the log carried no completion event"
        );
        assert!(
            std::path::Path::new("/tmp/tuna-e2e/recipe.json").exists(),
            "the shim recorded no recipe"
        );
    }

    #[test]
    fn recipe_roundtrip_and_field_serialization() {
        let mut recipe = Recipe::default();
        recipe.disk = "/dev/nvme0n1".into();
        recipe.filesystem = "btrfs".into();
        recipe.btrfs_subvolumes = true;
        recipe.target_imgref = "ghcr.io/tuna-os/albacore:stable".into();
        recipe.bootloader = "systemd".into();
        recipe.compose_fs_backend = true;
        recipe.flatpaks = vec!["org.mozilla.firefox".into()];
        recipe.additional_image_stores = vec!["/run/media/oci".into()];
        recipe.encryption.enc_type = "luks-passphrase".into();
        recipe.encryption.passphrase = "secret123".into();

        let json_str = serde_json::to_string(&recipe).unwrap();
        let restored: Recipe = serde_json::from_str(&json_str).unwrap();

        assert_eq!(restored.disk, recipe.disk);
        assert_eq!(restored.filesystem, recipe.filesystem);
        assert_eq!(restored.btrfs_subvolumes, recipe.btrfs_subvolumes);
        assert_eq!(restored.target_imgref, recipe.target_imgref);
        assert_eq!(restored.bootloader, recipe.bootloader);
        assert_eq!(restored.compose_fs_backend, recipe.compose_fs_backend);
        assert_eq!(restored.flatpaks, recipe.flatpaks);
        assert_eq!(restored.additional_image_stores, recipe.additional_image_stores);
        assert_eq!(restored.encryption.enc_type, recipe.encryption.enc_type);
        assert_eq!(restored.encryption.passphrase, recipe.encryption.passphrase);
        // The field whose absence broke this round trip. It was never
        // asserted, so the test failed on the unwrap rather than on a claim.
        assert_eq!(restored.image, recipe.image);
    }

    /// The live-ISO recipe is the one that omits `image` on the wire, so it
    /// is the shape that cannot be read back if the field loses `default`.
    #[test]
    fn live_iso_recipe_with_no_image_survives_the_round_trip() {
        let mut recipe = Recipe::default();
        recipe.disk = "/dev/sda".into();
        assert!(recipe.image.is_empty());

        let json_str = serde_json::to_string(&recipe).unwrap();
        assert!(
            !json_str.contains("\"image\""),
            "an empty image should not be serialized: {json_str}"
        );

        let restored: Recipe = serde_json::from_str(&json_str).unwrap();
        assert!(restored.image.is_empty());
        assert_eq!(restored.disk, recipe.disk);
    }

    /// A populated image must still make the trip, so `default` is not
    /// quietly swallowing a value that was present.
    #[test]
    fn a_populated_image_round_trips_unchanged() {
        let mut recipe = Recipe::default();
        recipe.image = "ghcr.io/tuna-os/albacore:latest".into();

        let json_str = serde_json::to_string(&recipe).unwrap();
        let restored: Recipe = serde_json::from_str(&json_str).unwrap();
        assert_eq!(restored.image, "ghcr.io/tuna-os/albacore:latest");
    }
}
