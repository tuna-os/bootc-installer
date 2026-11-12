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
mod source_check;
mod offline;
mod probe;
mod progress;
mod redact;
mod branding;
mod ui;
mod validate;
mod image_catalog;
mod hardware;
mod preflight;
mod tour;
mod i18n;

use cosmic::app::{Core, Settings, Task};
use cosmic::iced::{Length, Size};
use cosmic::prelude::*;
use cosmic::widget;
use cosmic::iced::futures::{SinkExt, Stream, StreamExt};
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command as TokioCommand;

pub use model::{DiskInfo, Recipe};

pub const APP_ID: &str = "org.tunaos.InstallerCosmic";

fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();

    let flags = Flags {
        capture: capture::Capture::from_env(),
    };
    if flags.capture.is_some() {
        // Before the first icon lookup, and before any other thread.
        capture::stage_repo_icons();
    }

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
    /// Blocking hardware gates (CPU/RAM/unsupported firmware). Shown only
    /// while a gate stands; GNOME opens a dedicated window instead.
    Requirements,
    Welcome,
    /// Image catalog (image.py / XFCE SourcePage). Skipped on live media
    /// and when the catalog offers fewer than two leaves.
    Image,
    /// Locale preflight (language.py).
    Language,
    /// Keyboard preflight (keyboard.py).
    Keyboard,
    /// Timezone preflight (timezone.py).
    Timezone,
    /// Connectivity preflight (network.py / conn_check.py). Skipped on
    /// live media: an offline install needs no network.
    Network,
    DiskSelect,
    Options,
    /// Username, full name and password: the recipe's `user` block.
    /// Conditional: skipped when the selected image (or a custom URL)
    /// provides its own first user.
    Account,
    /// Per-image tour carousel (views/tour.py). Skipped without slides.
    Tour,
    Confirm,
    Installing,
    Done,
}

impl Page {
    /// Wizard order. Also the capture order, so a new page cannot be added
    /// without appearing in the walkthrough.
    pub const ORDER: [Page; 14] = [
        Page::Requirements,
        Page::Welcome,
        Page::Image,
        Page::Language,
        Page::Keyboard,
        Page::Timezone,
        Page::Network,
        Page::DiskSelect,
        Page::Options,
        Page::Account,
        Page::Tour,
        Page::Confirm,
        Page::Installing,
        Page::Done,
    ];

    pub const fn slug(self) -> &'static str {
        match self {
            Page::Requirements => "requirements",
            Page::Welcome => "welcome",
            Page::Image => "image",
            Page::Language => "language",
            Page::Keyboard => "keyboard",
            Page::Timezone => "timezone",
            Page::Network => "network",
            Page::DiskSelect => "disk",
            Page::Options => "options",
            Page::Account => "account",
            Page::Tour => "tour",
            Page::Confirm => "confirm",
            Page::Installing => "installing",
            Page::Done => "done",
        }
    }

    /// The page's name in the header: a message id of `ui::copy`, shown
    /// through `i18n::tr`.
    pub const fn title(self) -> &'static str {
        use ui::copy;
        match self {
            Page::Requirements => copy::REQUIREMENTS_TITLE,
            Page::Welcome => copy::PAGE_WELCOME,
            Page::Image => copy::IMAGE_TITLE,
            Page::Language => copy::LANGUAGE_TITLE,
            Page::Keyboard => copy::KEYBOARD_TITLE,
            Page::Timezone => copy::TIMEZONE_TITLE,
            Page::Network => copy::NETWORK_TITLE,
            Page::DiskSelect => copy::DISK_TITLE,
            Page::Options => copy::OPTIONS_TITLE,
            Page::Account => copy::ACCOUNT_SECTION,
            Page::Tour => copy::TOUR_TITLE,
            Page::Confirm => copy::PAGE_CONFIRM,
            Page::Installing => copy::PAGE_INSTALLING,
            Page::Done => copy::PAGE_DONE,
        }
    }

    fn index(self) -> usize {
        Page::ORDER.iter().position(|p| *p == self).unwrap_or(0)
    }
}

/// The encryption types offered right now, in display order: fisherman's
/// encryption-choices.json (`validate::choices`, compiled in from
/// shared/recipe/). A `needs_tpm2` type is dropped entirely rather than shown
/// disabled when fisherman says no TPM 2.0 is usable (tunaOS#734): a dropdown
/// entry that produces an unenrollable recipe is worse than one that isn't
/// offered. What each one is called is branding copy
/// (`encryption_<type>_label` / `_description`), read in `ui.rs`.
pub fn available_encryption_choices(has_tpm: bool) -> Vec<&'static str> {
    validate::choices()
        .iter()
        .filter(|c| has_tpm || !validate::needs_tpm2(&c.enc_type))
        .map(|c| c.enc_type.as_str())
        .collect()
}

/// The options and account pages' fields as a partial recipe, for
/// `validate --json --partial -` on stdin (never argv: the passphrase is one
/// of them). The passphrase goes only with a needs_passphrase choice. Of the
/// account only the username goes: fisherman has no password rule, so the
/// password never leaves this process before the install.
fn partial_recipe(r: &Recipe) -> serde_json::Value {
    let mut encryption = serde_json::json!({ "type": r.encryption.enc_type });
    if validate::needs_passphrase(&r.encryption.enc_type) {
        encryption["passphrase"] = serde_json::json!(r.encryption.passphrase);
    }
    let username = r.user.as_ref().map_or("", |u| u.username.as_str());
    let mut partial = serde_json::json!({
        "hostname": r.hostname,
        "filesystem": r.filesystem,
        "btrfsSubvolumes": r.btrfs_subvolumes,
        "encryption": encryption,
        "user": { "username": username },
    });
    // fisherman refuses zfs without the opt-in, in the same fragment.
    let experimental = model::experimental_for(&r.filesystem);
    if !experimental.is_empty() {
        partial["experimental"] = serde_json::json!(experimental);
    }
    // The region picks, as the recipe has them (#292).
    if !r.locale.is_empty() {
        partial["locale"] = serde_json::json!(r.locale);
    }
    if let Some(keyboard) = &r.keyboard {
        partial["keyboard"] = serde_json::json!(keyboard);
    }
    if !r.timezone.is_empty() {
        partial["timezone"] = serde_json::json!(r.timezone);
    }
    partial
}

/// Whether a fisherman problem belongs to the account page (`user.*`). The
/// two pages share one check; each holds Continue only on its own fields.
fn is_account_field(field: &str) -> bool {
    field == "user" || field.starts_with("user.")
}

/// Whether a fisherman problem is about a region pick (`locale`,
/// `keyboard.*`, `timezone`). Confirm shows it; the options page does not
/// wait for it. fisherman refuses the same problem before any disk step.
fn is_region_field(field: &str) -> bool {
    field == "locale" || field == "timezone" || field == "keyboard" || field.starts_with("keyboard.")
}

impl TunaInstaller {
    /// fisherman's problem with a region pick, as the line Confirm shows.
    pub fn region_problem(&self) -> Option<&validate::Problem> {
        self.problems.iter().find(|p| is_region_field(&p.field))
    }
}

/// The account page's own rules (fisherman checks only the username's
/// form): a username and a password, the password typed the same twice.
fn account_complete(username: &str, password: &str, confirm: &str) -> bool {
    !username.is_empty() && !password.is_empty() && password == confirm
}

/// Whether the installer creates the first account
/// (`shared/catalog/README.md`, "The account").
///
/// - On live media there is no image page: the flag is the one of the leaf
///   whose reference is the booted image (`live.live_image`).
/// - Else it is the flag of the typed custom image, when the catalog has
///   it, or of the selected leaf.
/// - An image that the catalog does not have needs an account, and so does
///   an install with no image on record yet. A custom reference used to
///   skip the account, which left an image with nobody to sign in as.
fn account_required_for(
    catalog: &image_catalog::Catalog,
    live_image: Option<&str>,
    custom_image: &str,
    selected: Option<&image_catalog::ImageLeaf>,
) -> bool {
    if let Some(live) = live_image {
        return catalog.needs_user_creation(live);
    }
    let custom = custom_image.trim();
    if !custom.is_empty() {
        return catalog.needs_user_creation(custom);
    }
    selected.map_or(true, |leaf| leaf.needs_user_creation)
}

/// How an install ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Succeeded,
    /// The user stopped it. Not a failure: it has its own page (#299).
    Cancelled,
    Failed,
}

/// The wrapper's exit status as an outcome. `code` is `None` when a signal
/// ended the wrapper. fisherman exits 130 when it is cancelled
/// (shared/recipe/README.md), whoever asked. A signal, or a shell's
/// 128 + signal, is a cancel only after the user confirmed one: this
/// frontend signals the wrapper's group then, and that is what it looks
/// like. Any other signal is a crash.
pub fn install_outcome(code: Option<i32>, cancel_confirmed: bool) -> Outcome {
    match code {
        Some(0) => Outcome::Succeeded,
        Some(130) => Outcome::Cancelled,
        Some(c) if cancel_confirmed && c > 128 => Outcome::Cancelled,
        None if cancel_confirmed => Outcome::Cancelled,
        _ => Outcome::Failed,
    }
}

// -------------------------------------------------------------- messages ----

#[derive(Debug, Clone)]
pub enum Message {
    NextPage,
    BackPage,
    SelectDisk(usize),
    /// `fisherman probe --json` answered (shared/probe/README.md).
    Probed(Result<probe::Facts, String>),
    /// `fisherman validate --json --partial` answered for check number `.0`
    /// (shared/recipe/README.md). An answer for an older check is dropped.
    Validated(u64, Result<Vec<validate::Problem>, String>),
    /// `fisherman probe --json --source` answered for source check number
    /// `.0` (#266, #267): the request and the probe's stdout, or None when
    /// it failed. An answer for an older check is dropped.
    SourceChecked(u64, source_check::Request, Option<String>),
    /// The confirm page's install source: true is this computer's system
    /// from its bootc storage, false the download (#267).
    ReuseSelected(bool),
    HostnameChanged(String),
    FilesystemChanged(usize),
    EncryptionChanged(usize),
    PassphraseChanged(String),
    /// The options page's "Confirm passphrase" field.
    PassphraseConfirmChanged(String),
    TogglePassphraseVisible,
    /// The account page's fields.
    UsernameChanged(String),
    FullnameChanged(String),
    PasswordChanged(String),
    PasswordConfirmChanged(String),
    TogglePasswordVisible,
    /// The done page's "I have saved my recovery key" box.
    RecoveryAckToggled(bool),
    /// Put the recovery key on the clipboard.
    CopyRecoveryKey,
    StartInstall,
    /// The catalog choice (image.py / XFCE SourcePage).
    SelectImage(usize),
    /// A custom image reference, typed instead of picked. Non-empty wins
    /// over the catalog choice.
    CustomImageChanged(String),
    /// The image page's search box.
    ImageQueryChanged(String),
    /// "Continue anyway" on one overridable hardware gate (window_cpu /
    /// window_ram relaunch with IGNORE_CPU / IGNORE_RAM; here the override
    /// stays in-process, under the same names).
    OverrideGate(hardware::GateKind),
    /// Power off the machine (unsupported-firmware gate, poweroff dialog).
    PowerOff,
    /// Reboot into the firmware setup (poweroff dialog's firmware row).
    FirmwareSetup,
    /// The header's Exit button: confirm first, then quit — killing the
    /// install's process group on the way out when one is running
    /// (BootcWindow.__on_exit_clicked / __on_exit_response).
    RequestQuit,
    ConfirmQuit,
    CancelQuit,
    /// Copy the install log to the clipboard (dialog_output's copy affordance).
    CopyLog,
    /// Preflight lists arrived (localectl / timedatectl on the host).
    LocalesLoaded(Vec<String>),
    KeymapsLoaded(Vec<String>),
    TimezonesLoaded(Vec<String>),
    SelectLocale(usize),
    SelectKeymap(usize),
    TimezoneQueryChanged(String),
    SelectTimezone(usize),
    /// Connectivity recheck (conn_check's Recheck button).
    RecheckNetwork,
    /// The connectivity probe answered.
    NetworkChecked(bool),
    /// "Network settings" on the offline network page: the desktop's own
    /// tool, on the host, best effort (#301).
    OpenNetworkSettings,
    /// The progress page's Cancel: ask first (#299).
    RequestCancelInstall,
    /// "Cancel installation" in that dialog: signal the wrapper's group.
    ConfirmCancelInstall,
    /// "Keep installing" in that dialog.
    DismissCancelInstall,
    /// Tour carousel steps (views/tour.py): within the slides, then on.
    TourNext,
    TourBack,
    /// One line of fisherman's stdout, as it arrives.
    ///
    /// run_fisherman() used to be `.output()`: it waited for the process to
    /// exit and handed back everything at once, so the log appeared only when
    /// the install was already over and any progress bar fed from it would
    /// have jumped from nothing to done. Parsing alone would not have given
    /// this frontend a working bar; it needed the output to arrive while the
    /// install is running.
    InstallLine(String),
    /// The wrapper's exit code, or `None` when a signal ended it.
    InstallFinished(Result<Option<i32>, String>),
    Quit,
    /// The done page's Restart: `systemctl reboot` on the host.
    Reboot,
    /// The done page's store link.
    OpenUrl(String),
    /// Capture harness only — never reachable from the UI.
    Capture(capture::Message),
}

/// The options page's own rule: a needs_passphrase choice holds Continue
/// until the passphrase was typed the same twice. Other choices carry no
/// passphrase, so there is nothing to confirm.
fn passphrase_confirmed(enc_type: &str, passphrase: &str, confirm: &str) -> bool {
    !validate::needs_passphrase(enc_type) || passphrase == confirm
}

pub struct TunaInstaller {
    core: Core,
    page: Page,
    /// `Some` (the booted image, possibly "") when fisherman's probe says the
    /// host booted from live media (`live.is_live`); then the recipe leaves
    /// `image` empty and fisherman installs the running system.
    live_image: Option<String>,
    /// fisherman's problems with the options page's fields
    /// (`validate --json --partial`), and the number of the latest check.
    problems: Vec<validate::Problem>,
    validate_seq: u64,
    /// The source check (#266) and this computer's bootc storage (#267):
    /// the number of the latest check, its views (None while it runs) and
    /// whether the confirm page shows the section.
    source_seq: u64,
    source_view: Option<serde_json::Value>,
    store_view: Option<serde_json::Value>,
    /// The plain probe's output; the item of this computer's bootc storage
    /// that it offers as the install source (#267), and the user's pick.
    /// The download is the default.
    probe_output: Option<String>,
    reuse_source: Option<serde_json::Value>,
    reuse_selected: bool,
    source_visible: bool,
    recipe: Recipe,
    disks: Vec<DiskInfo>,
    selected_disk: Option<usize>,
    install_log: String,
    /// The install's position, parsed from fisherman's protocol
    /// (shared/progress/README.md). Before this the install page showed an
    /// indeterminate bar for the whole install — docs/PARITY.md gap #2.
    progress: progress::Progress,
    install_ok: bool,
    /// The install ended because the user cancelled it (`install_outcome`).
    install_cancelled: bool,
    installing: bool,
    /// The cancel dialog is open over the progress page.
    show_cancel_dialog: bool,
    /// The user confirmed a cancel and the wrapper's group was signalled.
    cancel_confirmed: bool,
    passphrase_hidden: bool,
    /// The passphrase typed a second time. Never in the recipe and never
    /// sent to fisherman: matching it is this frontend's only rule
    /// (shared/recipe/README.md), as on KDE and Niri.
    passphrase_confirm: String,
    /// The account page's fields. `recipe.user` is rebuilt from them on
    /// every change (`sync_user`), so a full name typed before the username
    /// is kept while the block itself is still left out.
    username: String,
    fullname: String,
    password: String,
    /// The password typed a second time. Never in the recipe.
    password_confirm: String,
    password_hidden: bool,
    /// Ticked by the user on the done page once they have written the
    /// recovery key down. It gates Restart (#129).
    recovery_ack: bool,
    /// fisherman's `tpm.usable`. Gates the two `tpm2-*` encryption choices.
    has_tpm: bool,
    /// fisherman's `system.unmet`: the welcome page warns about each one.
    unmet: Vec<String>,
    /// Why there are no disks, when the probe failed. No fallback scan.
    disk_error: Option<String>,
    /// Whether a probe answer (or failure) has arrived yet.
    probed: bool,
    /// `Some` only in capture mode. Its presence is also the hard interlock
    /// that stops the capture harness ever running a real install.
    capture: Option<capture::Capture>,
    /// Image catalog (shared/catalog/README.md): the default ref and the
    /// leaves. Empty when no catalog file was found.
    catalog: image_catalog::Catalog,
    /// `None` until the user, the branding or the catalog names a leaf.
    /// Never the first row by default.
    selected_image: Option<usize>,
    /// An image was on record at start-up (a default leaf, or the branding
    /// default with no catalog). Without one the image page must show.
    image_preselected: bool,
    /// A custom image reference, typed instead of picked. Wins over the leaf.
    custom_image: String,
    /// The image page's search box.
    image_query: String,
    /// The user typed a hostname: a new leaf's default no longer replaces it.
    hostname_edited: bool,
    /// An NVIDIA GPU is in this machine (`hardware::has_nvidia_gpu`).
    has_nvidia: bool,
    /// fisherman's `offline.images`: what the live media's stores hold.
    offline_images: Vec<String>,
    /// The first account's groups: shared/account/groups.json, or the
    /// operator's `user.groups`.
    user_groups: Vec<String>,
    /// The ISO's operator recipe (`<etc>/bootc-installer/recipe.json`),
    /// parsed once at start-up; `None` when missing or not JSON.
    operator_recipe: Option<serde_json::Value>,
    /// On live media, the leaf "install this system" applies
    /// (`image_catalog::live_leaf`); built by `sync_image`.
    live_leaf: Option<image_catalog::ImageLeaf>,
    /// "Continue anyway" overrides for the RAM/CPU gates.
    hw_overrides: hardware::Overrides,
    /// The exit-confirm state (RequestQuit): the view renders the confirm
    /// instead of the current page until this clears.
    show_exit_dialog: bool,
    /// Preflight lists and selections (localectl / timedatectl).
    locales: Vec<String>,
    selected_locale: Option<usize>,
    keymaps: Vec<String>,
    selected_keymap: Option<usize>,
    timezones: Vec<String>,
    tz_query: String,
    selected_timezone: Option<usize>,
    /// Connectivity state (conn_check): checking, and the last answer.
    net_checking: bool,
    net_online: Option<bool>,
    /// Tour carousel position within [`TunaInstaller::tour_slides`].
    tour_index: usize,
    /// The install wrapper's pid while it runs, so exiting mid-install can
    /// signal its process group (shared contract, spawn_wrapper).
    install_pid: std::sync::Arc<std::sync::Mutex<Option<u32>>>,
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
    pub fn install_cancelled(&self) -> bool {
        self.install_cancelled
    }
    pub fn show_cancel_dialog(&self) -> bool {
        self.show_cancel_dialog
    }
    pub fn cancel_confirmed(&self) -> bool {
        self.cancel_confirmed
    }
    pub fn installing(&self) -> bool {
        self.installing
    }
    pub fn passphrase_hidden(&self) -> bool {
        self.passphrase_hidden
    }
    pub fn passphrase_confirm(&self) -> &str {
        &self.passphrase_confirm
    }
    /// The confirmation matches, or the choice takes no passphrase.
    pub fn passphrases_match(&self) -> bool {
        passphrase_confirmed(
            &self.recipe.encryption.enc_type,
            &self.recipe.encryption.passphrase,
            &self.passphrase_confirm,
        )
    }
    pub fn username(&self) -> &str {
        &self.username
    }
    pub fn fullname(&self) -> &str {
        &self.fullname
    }
    pub fn password(&self) -> &str {
        &self.password
    }
    pub fn password_confirm(&self) -> &str {
        &self.password_confirm
    }
    pub fn password_hidden(&self) -> bool {
        self.password_hidden
    }
    /// The confirmation has text and differs from the password.
    pub fn password_mismatch(&self) -> bool {
        !self.password_confirm.is_empty() && self.password != self.password_confirm
    }
    /// Whether Continue is live on the account page: a username and a
    /// password typed the same twice (this frontend's rules), and no
    /// fisherman problem with the username.
    pub fn account_ok(&self) -> bool {
        account_complete(&self.username, &self.password, &self.password_confirm)
            && !self.problems.iter().any(|p| is_account_field(&p.field))
    }
    /// The recipe's `user` block, from the account page's fields.
    fn sync_user(&mut self) {
        self.recipe.user = model::user_block(
            &self.username,
            &self.fullname,
            &self.password,
            &self.user_groups,
        );
    }
    pub fn capturing(&self) -> bool {
        self.capture.is_some()
    }
    pub fn has_tpm(&self) -> bool {
        self.has_tpm
    }
    pub fn unmet(&self) -> &[String] {
        &self.unmet
    }
    pub fn disk_error(&self) -> Option<&str> {
        self.disk_error.as_deref()
    }
    pub fn probed(&self) -> bool {
        self.probed
    }
    pub fn images(&self) -> &[image_catalog::ImageLeaf] {
        &self.catalog.leaves
    }
    pub fn selected_image(&self) -> Option<usize> {
        self.selected_image
    }
    pub fn custom_image(&self) -> &str {
        &self.custom_image
    }
    pub fn image_query(&self) -> &str {
        &self.image_query
    }
    pub fn selected_leaf(&self) -> Option<&image_catalog::ImageLeaf> {
        self.selected_image.and_then(|i| self.catalog.leaves.get(i))
    }
    /// The leaf the recipe was built from: on live media the booted image's
    /// live leaf (`image_catalog::live_leaf`), else the typed custom image
    /// when the catalog has it, else the selected leaf.
    pub fn active_leaf(&self) -> Option<&image_catalog::ImageLeaf> {
        if !self.capturing() && self.live_image.is_some() {
            return self.live_leaf.as_ref();
        }
        let custom = self.custom_image.trim();
        if !custom.is_empty() {
            return self.catalog.find(custom).map(|i| &self.catalog.leaves[i]);
        }
        self.selected_leaf()
    }
    /// The filesystems the options page offers: the active leaf's, else
    /// this frontend's own list (shared/catalog/README.md, "Filesystem").
    pub fn filesystem_choices(&self) -> Vec<String> {
        self.active_leaf().map_or_else(
            || {
                image_catalog::OWN_FILESYSTEMS
                    .iter()
                    .map(|f| (*f).to_string())
                    .collect()
            },
            image_catalog::ImageLeaf::filesystem_choices,
        )
    }
    fn machine(&self) -> model::Machine {
        model::Machine {
            has_nvidia: self.has_nvidia,
            is_live: self.live_image.is_some(),
            offline_images: self.offline_images.clone(),
        }
    }
    pub fn hw_overrides(&self) -> hardware::Overrides {
        self.hw_overrides
    }
    /// The gates blocking the wizard right now.
    pub fn blocking_gates(&self) -> Vec<hardware::GateKind> {
        hardware::blocking_gates(&self.unmet, &self.hw_overrides)
    }
    pub fn show_exit_dialog(&self) -> bool {
        self.show_exit_dialog
    }
    pub fn locales(&self) -> &[String] {
        &self.locales
    }
    pub fn selected_locale(&self) -> Option<usize> {
        self.selected_locale
    }
    pub fn keymaps(&self) -> &[String] {
        &self.keymaps
    }
    pub fn selected_keymap(&self) -> Option<usize> {
        self.selected_keymap
    }
    pub fn timezones(&self) -> &[String] {
        &self.timezones
    }
    pub fn tz_query(&self) -> &str {
        &self.tz_query
    }
    pub fn selected_timezone(&self) -> Option<usize> {
        self.selected_timezone
    }
    pub fn net_checking(&self) -> bool {
        self.net_checking
    }
    pub fn net_online(&self) -> Option<bool> {
        self.net_online
    }
    pub fn tour_index(&self) -> usize {
        self.tour_index
    }
    /// Whether the account page is required (`account_required_for`).
    pub fn account_required(&self) -> bool {
        account_required_for(
            &self.catalog,
            // The capture walks every page with the live fixture loaded.
            if self.capturing() { None } else { self.live_image.as_deref() },
            &self.custom_image,
            self.selected_leaf(),
        )
    }
    /// The tour slides: the selected leaf's carousel, or none (and then
    /// the tour page is skipped).
    pub fn tour_slides(&self) -> Vec<tour::Slide> {
        self.selected_image
            .and_then(|i| self.catalog.leaves.get(i))
            .map(|l| tour::slides_from_carousel(&l.carousel))
            .unwrap_or_default()
    }
    /// A page earns its place in the walk only when its data does:
    /// conditional pages are skipped, never blank.
    pub fn page_visible(&self, page: Page) -> bool {
        match page {
            Page::Requirements => {
                !hardware::blocking_gates(&self.unmet, &self.hw_overrides).is_empty()
            }
            // Off live media the user chooses, unless one image was on
            // record at start-up and there is nothing else to choose.
            Page::Image => {
                self.live_image.is_none()
                    && (self.catalog.leaves.len() > 1 || !self.image_preselected)
            }
            // An installed bootc computer can copy its own system (#267):
            // the network check must not stop it before that choice.
            Page::Network => {
                self.live_image.is_none() && !source_check::offers_reuse(self.probe_output.as_deref())
            }
            Page::Account => self.account_required(),
            Page::Tour => !self.tour_slides().is_empty(),
            _ => true,
        }
    }

    /// Takes in a probe answer: the disks, TPM, requirements and live media
    /// together.
    fn apply_probe(&mut self, result: Result<probe::Facts, String>) {
        let first = !self.probed;
        let machine_before = self.machine();
        self.probed = true;
        match result {
            Ok(facts) => {
                self.disk_error = None;
                self.has_tpm = facts.tpm_usable;
                self.unmet = facts.unmet;
                // Live media is fisherman's answer. This used to be a
                // `bootc status` of our own plus /run/ostree-live and
                // /proc/cmdline, read inside the Flatpak sandbox.
                self.live_image = facts.is_live.then_some(facts.live_image);
                self.offline_images = facts.offline_images;
                self.probe_output = Some(facts.raw);
                // The image fields depend on live media and on the offline
                // stores. Build them again when those changed, and only
                // then: a later probe (the disk page runs one) must not
                // put the leaf's filesystem back over the user's choice.
                if first || self.machine() != machine_before {
                    self.sync_image();
                }
                let keep = self
                    .selected_disk
                    .and_then(|i| self.disks.get(i))
                    .map(|d| d.path.clone());
                self.disks = facts.disks;
                self.selected_disk = keep
                    .and_then(|p| self.disks.iter().position(|d| d.path == p))
                    .or((!self.disks.is_empty()).then_some(0));
            }
            Err(err) => {
                self.disk_error = Some(err);
                self.disks.clear();
                self.selected_disk = None;
            }
        }
        self.recipe.disk = self
            .selected_disk
            .and_then(|i| self.disks.get(i))
            .map(|d| d.path.clone())
            .unwrap_or_default();
        // GNOME decides the window before showing the wizard
        // (main.py::do_activate): with a gate standing and the user still
        // on the first page, the gates come first. Once the user has moved
        // on, the probe stays out of their way.
        if !self.capturing()
            && self.page == Page::Welcome
            && !hardware::blocking_gates(&self.unmet, &self.hw_overrides).is_empty()
        {
            self.page = Page::Requirements;
        }
    }

    /// fisherman's problem with a field of the options page, if it reported
    /// one: "hostname", or a prefix such as "encryption".
    pub fn problem(&self, field: &str) -> Option<&validate::Problem> {
        self.problems
            .iter()
            .find(|p| p.field == field || p.field.starts_with(&format!("{field}.")))
    }

    /// Whether the Options page is allowed to advance: fisherman knows no
    /// problem with the hostname, the filesystem or the encryption choice
    /// (an empty passphrase is `encryption_passphrase_required`). The rules
    /// are fisherman's; a check that could not run blocks nothing, because
    /// the install runs the same rules before it touches a disk.
    pub fn encryption_ok(&self) -> bool {
        // The username is the account page's, the region picks are
        // Confirm's: each holds its own page, not this one.
        !self
            .problems
            .iter()
            .any(|p| !is_account_field(&p.field) && !is_region_field(&p.field))
    }

    /// Whether Continue is live on the Options page: fisherman's rules
    /// (`encryption_ok`) and the passphrase confirmation, the one rule of
    /// this frontend. A mismatch is caught here, while it can be fixed,
    /// not at the first boot.
    pub fn options_ok(&self) -> bool {
        self.encryption_ok() && self.passphrases_match()
    }

    /// Asks fisherman about the options page after a pause in the typing,
    /// off the UI thread. Never in capture mode: nothing shells out there.
    fn check_fields(&mut self) -> Task<Message> {
        if self.capturing() {
            return Task::none();
        }
        self.validate_seq += 1;
        let seq = self.validate_seq;
        let mut partial = partial_recipe(&self.recipe);
        if self.reuse_selected() {
            // fisherman's static sourceReuse rules, before Install (#267).
            if let (Some(map), serde_json::Value::Object(fragment)) =
                (partial.as_object_mut(), source_check::reuse_fragment(&self.install_recipe()))
            {
                map.extend(fragment);
            }
        }
        Task::perform(
            async move {
                tokio::time::sleep(std::time::Duration::from_millis(300)).await;
                tokio::task::spawn_blocking(move || validate::check(&partial))
                    .await
                    .map_err(|e| format!("Task join error: {e}"))?
            },
            move |r| cosmic::action::app(Message::Validated(seq, r)),
        )
    }

    /// The hostname field's first value: the leaf's `default_hostname`,
    /// else the branding's. A hostname the user typed stays.
    fn apply_default_hostname(&mut self, leaf_default: &str) {
        if self.hostname_edited {
            return;
        }
        self.recipe.hostname = if leaf_default.is_empty() {
            branding::get().default_hostname.clone()
        } else {
            leaf_default.to_string()
        };
    }

    /// The recipe's image fields follow the image on record
    /// (`Recipe::apply_leaf`): every contract field of the leaf, and the
    /// NVIDIA rule for this machine. Called at init, on every selection
    /// change and when the probe's machine facts change, so Confirm and
    /// the install always see the choice the page shows.
    fn sync_image(&mut self) {
        let machine = self.machine();
        if !self.capturing() {
            if let Some(live) = self.live_image.clone() {
                // Live media installs the running system: `image` stays
                // empty. The booted image's live leaf (its catalog leaf with
                // the ISO recipe's layout over it) still says how
                // (bootloader, composefs, filesystem) and what updates
                // follow.
                let catalog_leaf = self.catalog.find(&live).map(|i| &self.catalog.leaves[i]);
                self.live_leaf =
                    image_catalog::live_leaf(catalog_leaf, &live, self.operator_recipe.as_ref());
                match self.live_leaf.clone() {
                    Some(leaf) => {
                        self.recipe.apply_leaf(&leaf, &machine);
                        self.apply_default_hostname(&leaf.default_hostname);
                    }
                    None => self.recipe.apply_unlisted_image(&live),
                }
                self.recipe.image.clear();
                return;
            }
        }
        let custom = self.custom_image.trim().to_string();
        let leaf = if custom.is_empty() {
            self.selected_leaf().cloned()
        } else {
            self.catalog.find(&custom).map(|i| self.catalog.leaves[i].clone())
        };
        if let Some(leaf) = leaf {
            self.recipe.apply_leaf(&leaf, &machine);
            self.apply_default_hostname(&leaf.default_hostname);
        } else if !custom.is_empty() {
            self.recipe.apply_unlisted_image(&custom);
            self.apply_default_hostname("");
        } else if self.catalog.leaves.is_empty() {
            // No catalog at all: the branding's image is the only one on
            // record. With a catalog, an image that is not in it selects
            // nothing and the user must choose.
            let default_image = branding::get().default_image.clone();
            self.recipe.apply_unlisted_image(&default_image);
        } else {
            self.recipe.apply_unlisted_image("");
        }
    }

    /// Side effects of arriving on a page: connectivity starts checking,
    /// the tour restarts its slides.
    fn on_enter_page(&mut self, page: Page) -> Task<Message> {
        match page {
            Page::Network => {
                if self.capturing() || self.live_image.is_some() {
                    return Task::none();
                }
                let image = self.recipe.image.clone();
                check_network_task(&mut self.net_checking, &mut self.net_online, false, false, image)
            }
            Page::Tour => {
                self.tour_index = 0;
                Task::none()
            }
            Page::Confirm => self.check_source(),
            _ => Task::none(),
        }
    }

    /// Asks fisherman about the selected source, off the UI thread. The
    /// probe gets the image references only; the recipe stays here.
    fn check_source(&mut self) -> Task<Message> {
        self.source_seq += 1;
        self.source_view = None;
        self.store_view = None;
        self.refresh_reuse();
        let recipe = self.install_recipe();
        let req = source_check::Request::from_recipe(&recipe, self.live_image.is_some());
        let args = req.probe_args();
        self.source_visible = !args.is_empty();
        if args.is_empty() || self.capturing() {
            return Task::none();
        }
        let seq = self.source_seq;
        Task::perform(
            async move {
                tokio::task::spawn_blocking(move || probe::run_output(&args).ok())
                    .await
                    .unwrap_or(None)
            },
            move |out| cosmic::action::app(Message::SourceChecked(seq, req.clone(), out)),
        )
    }

    /// Takes in the reply of source check `seq`. Public to the tests.
    pub fn apply_source_reply(&mut self, seq: u64, req: &source_check::Request, out: Option<&str>) {
        if seq != self.source_seq {
            return;
        }
        let view = source_check::check(out, req);
        if view["state"] == "stale" {
            return;
        }
        self.store_view = Some(source_check::bootc_store(out));
        self.source_view = Some(view);
    }

    /// The rows of the confirm page's Selected image section; empty when
    /// it is hidden.
    pub fn source_rows(&self) -> Vec<(String, String)> {
        if !self.source_visible {
            return Vec::new();
        }
        source_check::rows(self.source_view.as_ref(), self.store_view.as_ref(), self.reuse_selected())
    }

    /// Offers this computer's system as a second install source when the
    /// probe has an item that qualifies (#267). A different item, or none,
    /// drops the pick: the download stays the default.
    pub fn refresh_reuse(&mut self) {
        let update_ref = if self.recipe.target_imgref.is_empty() {
            self.recipe.image.clone()
        } else {
            self.recipe.target_imgref.clone()
        };
        let source = source_check::reuse_source(self.probe_output.as_deref(), &update_ref);
        if source.as_ref().map(|s| &s["digest"]) != self.reuse_source.as_ref().map(|s| &s["digest"]) {
            self.reuse_selected = false;
        }
        self.reuse_source = source;
    }

    /// The done page's lines after an install that exited 0 (#269): that
    /// nothing checked the new system, and what the `receipt` event says.
    pub fn receipt_lines(&self) -> Vec<String> {
        source_check::receipt_lines(self.progress.receipt.as_ref())
            .into_iter()
            .map(|(key, value)| branding::get().text_with(&key, &[("value", &value)]))
            .filter(|line| !line.is_empty())
            .collect()
    }

    /// The item that may be copied, as {ref, digest, platform}.
    pub fn reuse_source(&self) -> Option<&serde_json::Value> {
        self.reuse_source.as_ref()
    }

    /// The user picked this computer's system.
    pub fn reuse_selected(&self) -> bool {
        self.reuse_selected && self.reuse_source.is_some()
    }

    /// The recipe that fisherman gets: the wizard's, with the install
    /// source of the confirm page.
    pub fn install_recipe(&self) -> serde_json::Value {
        let mut recipe = self.recipe.clone();
        recipe.accept_experimental();
        let value = serde_json::to_value(&recipe).unwrap_or_default();
        match self.reuse_source.as_ref().filter(|_| self.reuse_selected) {
            Some(source) => source_check::apply_reuse(&value, source),
            None => value,
        }
    }

    /// fisherman's problem with the pick (`validate_source_reuse_<code>`).
    pub fn reuse_problem(&self) -> Option<&validate::Problem> {
        if !self.reuse_selected() {
            return None;
        }
        self.problems.iter().find(|p| p.code.starts_with("source_reuse_"))
    }

    /// Only a blocked source holds Install.
    pub fn source_blocked(&self) -> bool {
        self.source_view.as_ref().is_some_and(source_check::blocks_install) || self.reuse_problem().is_some()
    }

    fn advance(&mut self) -> (Option<Page>, Task<Message>) {
        let from = self.page.index();
        for i in (from + 1)..Page::ORDER.len() {
            let candidate = Page::ORDER[i];
            if self.page_visible(candidate) {
                self.page = candidate;
                let task = self.on_enter_page(candidate);
                return (Some(candidate), task);
            }
        }
        (None, Task::none())
    }

    fn retreat(&mut self) {
        let from = self.page.index();
        for i in (0..from).rev() {
            let candidate = Page::ORDER[i];
            if self.page_visible(candidate) {
                self.page = candidate;
                return;
            }
        }
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
        // the probe clears it on live media (apply_probe).
        let mut recipe = Recipe::default();
        {
            let b = branding::get();
            recipe.distro_id = b.id.clone();
            recipe.hostname = b.default_hostname.clone();
            recipe.image = b.default_image.clone();
        }
        // No additional_image_stores: left out, fisherman exposes the offline
        // stores it finds on the host (tuna-os/fisherman#276).

        // The image catalog (shared/catalog/README.md). The selection at
        // the start is the branding's default image, then the catalog's,
        // else nothing: never the first row. Nothing shells out: it is flat
        // files, read here.
        let mut catalog = image_catalog::Catalog::default();
        let mut operator_recipe = None;
        if !capturing {
            if let Some(loaded) = image_catalog::load_catalog() {
                catalog = loaded;
            }
            operator_recipe = model::read_operator_recipe(image_catalog::etc_dir());
        }
        let user_groups = model::groups_for(operator_recipe.as_ref());
        let default_image = branding::get().default_image.clone();
        let selected_image = catalog.default_index(&default_image);
        let image_preselected =
            selected_image.is_some() || (catalog.leaves.is_empty() && !default_image.is_empty());
        let mut app = Self {
            core,
            page: Page::Welcome,
            live_image: None,
            problems: Vec::new(),
            validate_seq: 0,
            source_seq: 0,
            source_view: None,
            store_view: None,
            probe_output: None,
            reuse_source: None,
            reuse_selected: false,
            source_visible: false,
            recipe,
            selected_disk: None,
            disks: Vec::new(),
            install_log: String::new(),
            progress: progress::Progress::new(branding::name()),
            install_ok: false,
            install_cancelled: false,
            installing: false,
            show_cancel_dialog: false,
            cancel_confirmed: false,
            passphrase_hidden: true,
            passphrase_confirm: String::new(),
            username: String::new(),
            fullname: String::new(),
            password: String::new(),
            password_confirm: String::new(),
            password_hidden: true,
            recovery_ack: false,
            // Until the probe answers: no TPM choices, no warning.
            has_tpm: false,
            unmet: Vec::new(),
            disk_error: None,
            probed: false,
            capture: flags.capture,
            catalog,
            selected_image,
            image_preselected,
            custom_image: String::new(),
            image_query: String::new(),
            hostname_edited: false,
            has_nvidia: !capturing && hardware::has_nvidia_gpu(),
            offline_images: Vec::new(),
            user_groups,
            operator_recipe,
            live_leaf: None,
            hw_overrides: hardware::Overrides::default(),
            show_exit_dialog: false,
            locales: Vec::new(),
            selected_locale: None,
            keymaps: Vec::new(),
            selected_keymap: None,
            timezones: Vec::new(),
            tz_query: String::new(),
            selected_timezone: None,
            net_checking: false,
            net_online: None,
            tour_index: 0,
            install_pid: std::sync::Arc::new(std::sync::Mutex::new(None)),
        };
        // The selected leaf's fields, before the probe answers.
        app.sync_image();
        if capturing {
            // The shared laptop fixture, through the same reader. A capture
            // without it would photograph an error, so refuse.
            let facts = capture::fixture_probe();
            if let Err(e) = &facts {
                eprintln!("capture: probe fixture unreadable: {e}");
                std::process::exit(2);
            }
            app.apply_probe(facts);
        }

        // The product name from the branding contract (branding.json, then
        // os-release), never a literal — see `branding`.
        let window_title = i18n::tr_with(ui::copy::WINDOW_TITLE, &[("product", branding::name())]);
        let mut tasks = vec![app.set_window_title(window_title.clone())];
        if app.capture.is_some() {
            tasks.push(capture::begin());
        } else {
            tasks.push(Task::perform(Self::probe(), |r| {
                cosmic::action::app(Message::Probed(r))
            }));
            tasks.push(app.check_fields());
            // Preflight lists (localectl / timedatectl on the host), off
            // the UI thread. Empty answers are fine: each page renders its
            // empty state and still advances.
            tasks.push(Task::perform(
                async move {
                    tokio::task::spawn_blocking(preflight::load_locales)
                        .await
                        .unwrap_or_default()
                },
                |v| cosmic::action::app(Message::LocalesLoaded(v)),
            ));
            tasks.push(Task::perform(
                async move {
                    tokio::task::spawn_blocking(preflight::load_keymaps)
                        .await
                        .unwrap_or_default()
                },
                |v| cosmic::action::app(Message::KeymapsLoaded(v)),
            ));
            tasks.push(Task::perform(
                async move {
                    tokio::task::spawn_blocking(preflight::load_timezones)
                        .await
                        .unwrap_or_default()
                },
                |v| cosmic::action::app(Message::TimezonesLoaded(v)),
            ));
        }
        app.set_header_title(window_title);

        (app, Task::batch(tasks))
    }

    fn header_start(&self) -> Vec<Element<'_, Message>> {
        // The step indicator lives in the COSMIC header bar rather than being
        // drawn by hand in the page body, which is what makes this read as a
        // COSMIC app instead of a generic iced window.
        let spacing = cosmic::theme::active().cosmic().spacing;
        vec![widget::text::caption(i18n::tr_with(ui::copy::HEADER_STEP,
            &[
                ("n", &(self.page.index() + 1).to_string()),
                ("total", &Page::ORDER.len().to_string()),
                ("title", &i18n::tr(self.page.title())),
            ],
        ))
        .apply(widget::container)
        .padding([0, spacing.space_xs])
        .into()]
    }

    fn header_end(&self) -> Vec<Element<'_, Message>> {
        vec![
            widget::progress_bar::determinate_linear(
                (self.page.index() as f32 + 1.0) / Page::ORDER.len() as f32,
            )
            .width(Length::Fixed(120.0))
            .into(),
            // GNOME's header exit (btn_exit): confirm first, and kill the
            // install's process group when one is running.
            widget::button::standard(i18n::tr(crate::ui::copy::EXIT_BUTTON))
                .on_press(Message::RequestQuit)
                .into(),
        ]
    }

    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::NextPage => {
                let (next, task) = self.advance();
                if next == Some(Page::DiskSelect) && !self.capturing() {
                    // Again on entering the page, so a disk plugged in
                    // after start-up appears.
                    return Task::batch(vec![
                        task,
                        Task::perform(Self::probe(), |r| {
                            cosmic::action::app(Message::Probed(r))
                        }),
                    ]);
                }
                task
            }
            Message::BackPage => {
                self.retreat();
                Task::none()
            }
            Message::SelectImage(idx) => {
                if idx < self.catalog.leaves.len() {
                    self.selected_image = Some(idx);
                    self.sync_image();
                }
                // The leaf can change the filesystem and the hostname:
                // ask fisherman about the new values.
                self.check_fields()
            }
            Message::CustomImageChanged(s) => {
                self.custom_image = s;
                self.sync_image();
                self.check_fields()
            }
            Message::ImageQueryChanged(q) => {
                // A selected row stays selected while the query hides it.
                self.image_query = q;
                Task::none()
            }
            Message::OverrideGate(kind) => {
                // Window_cpu / window_ram's "continue anyway", kept under
                // the same IGNORE_* names the probe contract documents.
                match kind {
                    hardware::GateKind::Ram => self.hw_overrides.ram = true,
                    hardware::GateKind::Cpu => self.hw_overrides.cpu = true,
                    // Unsupported firmware offers no way forward — only
                    // power off (window_unsupported has no continue).
                    hardware::GateKind::Unsupported => {}
                }
                if let Some(name) = hardware::override_env(kind) {
                    tracing::debug!("hardware gate overridden ({name})");
                }
                // With the last gate overridden the page stops being
                // visible, so move on; with gates standing the page stays.
                if hardware::blocking_gates(&self.unmet, &self.hw_overrides).is_empty() {
                    let (_, task) = self.advance();
                    task
                } else {
                    Task::none()
                }
            }
            Message::PowerOff => {
                spawn_host(&hardware::poweroff_command());
                Task::none()
            }
            Message::FirmwareSetup => {
                spawn_host(&hardware::firmware_setup_command());
                Task::none()
            }
            Message::RequestQuit => {
                // Mirror __is_done: no confirm once finished.
                if self.page == Page::Done {
                    std::process::exit(i32::from(!self.install_ok));
                }
                self.show_exit_dialog = true;
                Task::none()
            }
            Message::ConfirmQuit => {
                self.show_exit_dialog = false;
                // Terminate fisherman before quitting, as __on_exit_response
                // does through view_progress.terminate(): the wrapper leads
                // its own group, so signalling the group reaches the install
                // and not this process.
                if self.installing {
                    let pid = self.install_pid.lock().unwrap().take();
                    if let Some(pid) = pid {
                        let _ = hardware::terminate_process_group(pid);
                    }
                }
                std::process::exit(i32::from(!self.install_ok));
            }
            Message::CancelQuit => {
                self.show_exit_dialog = false;
                Task::none()
            }
            Message::CopyLog => {
                // Without the recovery key: a copied log ends up in a bug
                // report (redact.rs, #337).
                cosmic::iced::clipboard::write(redact::recovery_key(
                    &self.install_log,
                    &self.progress.recovery_key,
                ))
            }
            Message::LocalesLoaded(locales) => {
                // The session locale first, so the current choice stays
                // selected instead of resetting to the top of the list.
                let current = std::env::var("LANG").unwrap_or_default();
                let ordered = preflight::order_locales(locales, &current);
                self.selected_locale = (!ordered.is_empty()).then_some(0);
                self.locales = ordered;
                Task::none()
            }
            Message::KeymapsLoaded(keymaps) => {
                self.selected_keymap = if keymaps.is_empty() {
                    None
                } else {
                    Some(keymaps.iter().position(|k| k == "us").unwrap_or(0))
                };
                self.keymaps = keymaps;
                Task::none()
            }
            Message::TimezonesLoaded(timezones) => {
                self.timezones = timezones;
                Task::none()
            }
            Message::SelectLocale(idx) => {
                if idx >= self.locales.len() {
                    return Task::none();
                }
                {
                    self.selected_locale = Some(idx);
                    let locale = self.locales[idx].clone();
                    // A pick goes into the recipe too (#292).
                    self.recipe.locale.clone_from(&locale);
                    // The capture harness picks too; it must not change the
                    // runner's own settings.
                    if !self.capturing() {
                        preflight::apply_best_effort(&preflight::apply_locale_command(&locale));
                    }
                }
                // fisherman checks the pick now, not at Install.
                self.check_fields()
            }
            Message::SelectKeymap(idx) => {
                if idx >= self.keymaps.len() {
                    return Task::none();
                }
                {
                    self.selected_keymap = Some(idx);
                    let keymap = self.keymaps[idx].clone();
                    self.recipe.keyboard = Some(model::Keyboard {
                        layout: keymap.clone(),
                        ..model::Keyboard::default()
                    });
                    if !self.capturing() {
                        preflight::apply_best_effort(&preflight::apply_keymap_command(&keymap));
                    }
                }
                // fisherman checks the pick now, not at Install.
                self.check_fields()
            }
            Message::TimezoneQueryChanged(q) => {
                self.tz_query = q;
                Task::none()
            }
            Message::SelectTimezone(idx) => {
                if idx >= self.timezones.len() {
                    return Task::none();
                }
                {
                    self.selected_timezone = Some(idx);
                    let zone = self.timezones[idx].clone();
                    self.recipe.timezone.clone_from(&zone);
                    if !self.capturing() {
                        preflight::apply_best_effort(&preflight::apply_timezone_command(&zone));
                    }
                }
                // fisherman checks the pick now, not at Install.
                self.check_fields()
            }
            Message::RecheckNetwork => {
                let capturing = self.capturing();
                let is_live = self.live_image.is_some();
                let image = self.recipe.image.clone();
                check_network_task(&mut self.net_checking, &mut self.net_online, capturing, is_live, image)
            }
            Message::NetworkChecked(online) => {
                self.net_checking = false;
                self.net_online = Some(online);
                Task::none()
            }
            Message::OpenNetworkSettings => {
                // Best effort: the page still has Recheck when no tool
                // starts.
                spawn_host(&hardware::network_settings_command());
                Task::none()
            }
            Message::RequestCancelInstall => {
                if self.installing && !self.cancel_confirmed {
                    self.show_cancel_dialog = true;
                }
                Task::none()
            }
            Message::DismissCancelInstall => {
                self.show_cancel_dialog = false;
                Task::none()
            }
            Message::ConfirmCancelInstall => {
                self.show_cancel_dialog = false;
                // The wrapper leads its own process group, so the signal
                // reaches the whole install and not this process. fisherman
                // then cleans up (unmounts, closes LUKS) and the wrapper
                // ends; InstallFinished shows the cancelled page. The pid
                // stays in the slot until the wrapper is reaped.
                let pid = *self.install_pid.lock().unwrap();
                if let (true, Some(pid)) = (self.installing, pid) {
                    if hardware::terminate_process_group(pid).is_ok() {
                        self.cancel_confirmed = true;
                    }
                }
                Task::none()
            }
            Message::TourNext => {
                if self.tour_index + 1 < self.tour_slides().len() {
                    self.tour_index += 1;
                    Task::none()
                } else {
                    let (_, task) = self.advance();
                    task
                }
            }
            Message::TourBack => {
                if self.tour_index > 0 {
                    self.tour_index -= 1;
                } else {
                    self.retreat();
                }
                Task::none()
            }
            Message::SelectDisk(idx) => {
                if let Some(disk) = self.disks.get(idx) {
                    self.selected_disk = Some(idx);
                    self.recipe.disk = disk.path.clone();
                }
                Task::none()
            }
            Message::Probed(result) => {
                self.apply_probe(result);
                Task::none()
            }
            Message::SourceChecked(seq, req, out) => {
                self.apply_source_reply(seq, &req, out.as_deref());
                Task::none()
            }
            Message::ReuseSelected(selected) => {
                self.reuse_selected = selected && self.reuse_source.is_some();
                // fisherman checks the pick, and the source check asks
                // about the new source.
                Task::batch([self.check_fields(), self.check_source()])
            }
            Message::Validated(seq, result) => {
                if seq == self.validate_seq {
                    self.problems = result.unwrap_or_else(|e| {
                        tracing::warn!("fisherman validate could not run: {e}");
                        Vec::new()
                    });
                }
                Task::none()
            }
            Message::HostnameChanged(h) => {
                self.hostname_edited = true;
                self.recipe.hostname = h;
                self.check_fields()
            }
            Message::FilesystemChanged(idx) => {
                // A position in the list the page drew: the active leaf's
                // choices (`filesystem_choices`).
                if let Some(fs) = self.filesystem_choices().get(idx) {
                    self.recipe.btrfs_subvolumes = fs == "btrfs";
                    self.recipe.filesystem.clone_from(fs);
                }
                self.check_fields()
            }
            Message::EncryptionChanged(idx) => {
                // Recompute the same has_tpm-filtered list ui.rs built the
                // dropdown from, so `idx` (a position in THAT list) resolves
                // to the same choice the user actually saw and clicked.
                let choices = available_encryption_choices(self.has_tpm);
                if let Some(choice) = choices.get(idx) {
                    self.recipe.encryption.enc_type = choice.to_string();
                    // Only a needs_passphrase choice carries a passphrase;
                    // clear it for the others so a stale value from a
                    // previous choice can't linger into the recipe.
                    if !validate::needs_passphrase(choice) {
                        self.recipe.encryption.passphrase.clear();
                        self.passphrase_confirm.clear();
                    }
                }
                self.check_fields()
            }
            Message::PassphraseChanged(p) => {
                self.recipe.encryption.passphrase = p;
                self.check_fields()
            }
            Message::PassphraseConfirmChanged(p) => {
                // Not a field fisherman checks, so no validate round-trip.
                self.passphrase_confirm = p;
                Task::none()
            }
            Message::TogglePassphraseVisible => {
                self.passphrase_hidden = !self.passphrase_hidden;
                Task::none()
            }
            Message::UsernameChanged(u) => {
                self.username = u;
                self.sync_user();
                self.check_fields()
            }
            Message::FullnameChanged(f) => {
                // Free text; fisherman has no rule for it.
                self.fullname = f;
                self.sync_user();
                Task::none()
            }
            Message::PasswordChanged(p) => {
                // Not sent to validate: fisherman accepts any password, and
                // this frontend's rules are local (account_ok).
                self.password = p;
                self.sync_user();
                Task::none()
            }
            Message::PasswordConfirmChanged(p) => {
                self.password_confirm = p;
                Task::none()
            }
            Message::TogglePasswordVisible => {
                self.password_hidden = !self.password_hidden;
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
                // One install at a time.
                if self.installing {
                    return Task::none();
                }
                self.page = Page::Installing;
                self.installing = true;
                self.install_cancelled = false;
                self.cancel_confirmed = false;
                self.show_cancel_dialog = false;
                self.progress.reset();
                let recipe = self.install_recipe();
                let pid_slot = self.install_pid.clone();
                let live = self.live_image.is_some();
                Task::stream(Self::stream_fisherman(recipe, pid_slot, live).map(cosmic::action::app))
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
                self.show_cancel_dialog = false;
                match result {
                    Ok(code) => {
                        let outcome = install_outcome(code, self.cancel_confirmed);
                        self.install_ok = outcome == Outcome::Succeeded;
                        self.install_cancelled = outcome == Outcome::Cancelled;
                        let how = code.map_or("a signal".to_string(), |c| format!("code {c}"));
                        self.install_log
                            .push_str(&format!("\n=== fisherman exited with {how} ===\n"));
                    }
                    Err(e) => {
                        self.install_ok = false;
                        self.install_cancelled = false;
                        self.install_log.push_str(&format!("\n=== Error: {e} ===\n"));
                    }
                }
                offline::persist_install_log(&self.install_log, &self.progress.recovery_key);
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
        // The exit confirm (dialog_poweroff's sibling in GNOME's main
        // window) replaces the page until it is answered.
        if self.show_exit_dialog {
            return ui::exit_confirm(self);
        }
        // The cancel dialog asks before a half-written disk is abandoned.
        if self.show_cancel_dialog {
            return ui::cancel_confirm(self);
        }
        ui::view(self)
    }
}

// -------------------------------------------------------- async helpers ----

impl TunaInstaller {
    /// `fisherman probe --json`, off the UI thread (shared/probe/README.md).
    async fn probe() -> Result<probe::Facts, String> {
        tokio::task::spawn_blocking(probe::run)
            .await
            .map_err(|e| format!("Task join error: {e}"))?
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
    /// into the same stream line by line (see `merged_lines`), which the
    /// parser passes through untouched.
    fn stream_fisherman(
        recipe: serde_json::Value,
        pid_slot: std::sync::Arc<std::sync::Mutex<Option<u32>>>,
        live: bool,
    ) -> impl Stream<Item = Message> {
        cosmic::iced::stream::channel(64, async move |mut output| {
            // `install_recipe()`: the experimental opt-ins are in it.
            let json = match serde_json::to_string_pretty(&recipe) {
                Ok(json) => json,
                Err(e) => {
                    let _ = output.send(Message::InstallFinished(Err(e.to_string()))).await;
                    return;
                }
            };
            // The one resolver (offline::fisherman_argv): pkexec, or
            // `sudo -n` on native live media, inside a bash this user can
            // signal; in a Flatpak the staged and verified copy, on the
            // host. The recipe goes to the wrapper's stdin, never to a
            // file: it may hold a passphrase (tuna-os/fisherman#276).
            let cmd = match offline::fisherman(offline::Use::Install, live) {
                Ok(cmd) => cmd,
                Err(e) => {
                    let _ = output
                        .send(Message::InstallFinished(Err(format!(
                            "Failed to prepare fisherman: {e}"
                        ))))
                        .await;
                    return;
                }
            };
            let mut child = match spawn_wrapper(&cmd, json.into_bytes()).await {
                Ok(child) => {
                    // Published for the exit path: ConfirmQuit signals this
                    // group, which is what stops the install instead of
                    // orphaning it.
                    *pid_slot.lock().unwrap() = child.id();
                    child
                }
                Err(e) => {
                    let _ = output
                        .send(Message::InstallFinished(Err(format!(
                            "Failed to run fisherman: {e}"
                        ))))
                        .await;
                    return;
                }
            };

            // Both pipes at once. stdout used to be read to EOF before stderr
            // was touched, so a fisherman that filled the stderr pipe (64 KiB)
            // blocked on write while this waited for stdout to end: both
            // processes hung for good. stderr still matters — fisherman writes
            // its failure summary there.
            let mut lines = merged_lines(child.stdout.take(), child.stderr.take());
            while let Some(line) = lines.recv().await {
                if output.send(Message::InstallLine(line)).await.is_err() {
                    break;
                }
            }

            // `None` when a signal ended the wrapper (a confirmed cancel).
            let code = match child.wait().await {
                Ok(status) => status.code(),
                Err(e) => {
                    let _ = output.send(Message::InstallFinished(Err(e.to_string()))).await;
                    return;
                }
            };
            // The wrapper is reaped: clear the slot so a later exit no
            // longer signals a recycled pid.
            *pid_slot.lock().unwrap() = None;
            if code != Some(0) {
                tracing::error!("fisherman exited with {code:?}");
            }
            let _ = output.send(Message::InstallFinished(Ok(code))).await;
        })
    }
}

/// Spawn a host command detached: power off, firmware setup, and the
/// preflight applies never hold the UI thread.
fn spawn_host(argv: &[String]) {
    if let Some((program, args)) = argv.split_first() {
        if let Err(e) = std::process::Command::new(program).args(args).spawn() {
            tracing::warn!("host command {argv:?} failed to start: {e}");
        }
    }
}

/// (Re)start the connectivity probe off the UI thread. In capture mode or
/// on live media there is nothing to check: the page shows its seeded or
/// skipped state instead.
fn check_network_task(
    checking: &mut bool,
    online: &mut Option<bool>,
    capturing: bool,
    is_live: bool,
    image: String,
) -> Task<Message> {
    if capturing || is_live {
        return Task::none();
    }
    *checking = true;
    *online = None;
    Task::perform(
        async move {
            // The registry of the selected image first (#301).
            tokio::task::spawn_blocking(move || preflight::check_connectivity(&image))
                .await
                .unwrap_or(false)
        },
        |ok| cosmic::action::app(Message::NetworkChecked(ok)),
    )
}

/// Start fisherman's wrapper with piped output, as the leader of its own
/// process group, and hand it `stdin_data` (the recipe) on stdin, closed
/// after: fisherman reads to EOF.
///
/// The wrapper is the only process of the install this user can signal;
/// fisherman runs as root and cancels when its parent dies
/// (tuna-os/fisherman#267). The shared contract is "kill your wrapper's
/// process group", which must never be the installer's own group. This
/// The progress page's Cancel (after its dialog) and the header's Exit
/// both signal that group (`hardware::terminate_process_group`).
async fn spawn_wrapper(argv: &[String], stdin_data: Vec<u8>) -> std::io::Result<tokio::process::Child> {
    use tokio::io::AsyncWriteExt;
    let mut child = TokioCommand::new(&argv[0])
        .args(&argv[1..])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()?;
    if let Some(mut stdin) = child.stdin.take() {
        // A wrapper that is already gone says why through its exit code.
        let _ = stdin.write_all(&stdin_data).await;
        let _ = stdin.shutdown().await;
    }
    Ok(child)
}

/// Every line from a child's stdout and stderr, read concurrently.
///
/// Each pipe gets its own task, so neither can fill up while the other is
/// being waited on. Lines are interleaved in arrival order; a line is never
/// split across the two streams. The tasks keep draining after the receiver
/// is dropped, so an abandoned install page cannot leave the child blocked on
/// a full pipe.
fn merged_lines<O, E>(stdout: Option<O>, stderr: Option<E>) -> tokio::sync::mpsc::UnboundedReceiver<String>
where
    O: tokio::io::AsyncRead + Unpin + Send + 'static,
    E: tokio::io::AsyncRead + Unpin + Send + 'static,
{
    let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
    if let Some(stdout) = stdout {
        let tx = tx.clone();
        tokio::spawn(async move {
            let mut lines = BufReader::new(stdout).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let _ = tx.send(line);
            }
        });
    }
    if let Some(stderr) = stderr {
        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let _ = tx.send(line);
            }
        });
    }
    rx
}

#[cfg(test)]
mod tests {
    #[test]
    fn override_makes_all_four_choices_available() {
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
        assert!(!recipe.selinux_disabled);

        let json_str = serde_json::to_string(&recipe).unwrap();
        let json: serde_json::Value = serde_json::from_str(&json_str).unwrap();

        assert_eq!(json["filesystem"], "xfs");
        assert_eq!(json["encryption"]["type"], "none");
        assert_eq!(json["distroID"], "linux");
        assert_eq!(json["hostname"], "linux");
        assert_eq!(json["selinuxDisabled"], false);
        assert!(json.get("image").is_none());
        assert!(json.get("targetImgref").is_none());
        assert!(json.get("bootloader").is_none());
        // No list on record: no key. `[]` would tell fisherman to copy no
        // Flatpak at all.
        assert!(json.get("flatpaks").is_none());
        assert!(json.get("flatpakVarPath").is_none());
        assert!(json.get("imageType").is_none());
        let mut none = Recipe::default();
        none.flatpaks = Some(Vec::new());
        assert_eq!(serde_json::to_value(&none).unwrap()["flatpaks"], serde_json::json!([]));
    }

    #[test]
    fn a_passphrase_choice_needs_the_passphrase_twice() {
        use super::passphrase_confirmed;
        for t in ["luks-passphrase", "tpm2-luks-passphrase"] {
            assert!(passphrase_confirmed(t, "s3cret", "s3cret"), "{t}");
            assert!(!passphrase_confirmed(t, "s3cret", "s3cre"), "{t}");
            assert!(!passphrase_confirmed(t, "s3cret", ""), "{t}");
        }
        // No passphrase to confirm: never held by the confirmation.
        for t in ["", "none", "tpm2-luks"] {
            assert!(passphrase_confirmed(t, "", "leftover"), "{t}");
        }
    }

    #[test]
    fn encryption_choices_filtering() {
        let without_tpm = available_encryption_choices(false);
        assert_eq!(without_tpm.len(), 2);
        assert!(without_tpm.iter().all(|c| !validate::needs_tpm2(c)));
        assert_eq!(without_tpm[0], "none");
        assert_eq!(without_tpm[1], "luks-passphrase");

        let with_tpm = available_encryption_choices(true);
        assert_eq!(with_tpm.len(), 4);
        assert_eq!(with_tpm[2], "tpm2-luks");
        assert_eq!(with_tpm[3], "tpm2-luks-passphrase");
    }

    /// The process group a pid belongs to: field 5 of /proc/<pid>/stat.
    fn pgrp_of(pid: &str) -> u32 {
        let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
        // comm (field 2) may hold spaces; the rest follows its closing ')'.
        let rest = &stat[stat.rfind(')').unwrap() + 2..];
        rest.split_whitespace().nth(2).unwrap().parse().unwrap()
    }

    #[test]
    fn wrapper_leads_its_own_process_group() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            let mut child = super::spawn_wrapper(&["sleep".to_string(), "30".to_string()], Vec::new())
                .await
                .expect("sleep");
            let pid = child.id().unwrap();
            assert_eq!(pgrp_of(&pid.to_string()), pid, "the wrapper is not a group leader");
            assert_ne!(pgrp_of(&pid.to_string()), pgrp_of("self"));
            // Signalling that group reaches the wrapper, not this process.
            let killed = std::process::Command::new("kill")
                .args(["-TERM", "--", &format!("-{pid}")])
                .status()
                .unwrap();
            assert!(killed.success());
            let status = child.wait().await.unwrap();
            use std::os::unix::process::ExitStatusExt;
            assert_eq!(status.signal(), Some(15));
        });
    }

    /// fisherman reads the recipe on stdin (`fisherman -`): what the wrapper
    /// gets on stdin is the recipe, and stdin is closed so fisherman's read
    /// to EOF ends.
    #[test]
    fn the_recipe_goes_to_the_wrappers_stdin() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            let mut recipe = Recipe::default();
            recipe.encryption.enc_type = "luks-passphrase".into();
            recipe.encryption.passphrase = "s3cret".into();
            let json = serde_json::to_string(&recipe).unwrap();
            let child = super::spawn_wrapper(&["cat".to_string()], json.clone().into_bytes())
                .await
                .expect("cat");
            let out = child.wait_with_output().await.unwrap();
            assert!(out.status.success());
            assert_eq!(String::from_utf8_lossy(&out.stdout), json);
            // The install's wrapper ends in `fisherman -`: stdin, no file.
            let argv = super::offline::fisherman(super::offline::Use::Install, false).unwrap();
            assert!(argv.last().unwrap().ends_with("fisherman -; exit $?"), "{argv:?}");
        });
    }

    /// The options page asks fisherman, and only its answer blocks Continue.
    #[test]
    fn the_partial_recipe_and_its_problems() {
        let r = Recipe {
            hostname: "my_pc".into(),
            encryption: crate::model::Encryption {
                enc_type: "tpm2-luks".into(),
                passphrase: "stale".into(),
            },
            ..Recipe::default()
        };
        let problems = vec![validate::Problem {
            field: "encryption.passphrase".into(),
            code: "encryption_passphrase_required".into(),
            message: "m".into(),
        }];
        // Only the fields the page has; a passphrase only for a type that
        // takes one.
        let partial = super::partial_recipe(&r);
        assert_eq!(
            partial,
            serde_json::json!({
                "hostname": "my_pc", "filesystem": "xfs",
                "btrfsSubvolumes": false, "encryption": {"type": "tpm2-luks"},
                "user": {"username": ""},
            })
        );
        let zfs = Recipe { filesystem: "zfs".into(), ..r.clone() };
        assert_eq!(super::partial_recipe(&zfs)["experimental"], serde_json::json!(["zfs"]));
        let mut with_passphrase = r.clone();
        with_passphrase.encryption.enc_type = "tpm2-luks-passphrase".into();
        assert_eq!(super::partial_recipe(&with_passphrase)["encryption"]["passphrase"], "stale");
        let enc_problem = problems.iter().find(|p| p.field.starts_with("encryption."));
        assert!(enc_problem.is_some());
        assert_eq!(
            enc_problem.unwrap().render(),
            branding::get().text("validate_encryption_passphrase_required")
        );
        assert_eq!(partial["encryption"].get("passphrase"), None);
    }

    /// A child that writes more than a pipe buffer to stderr before it
    /// writes anything to stdout. Reading stdout to EOF first deadlocked:
    /// the child blocked on the full stderr pipe and never closed stdout.
    #[test]
    fn merged_lines_drains_a_full_stderr_pipe_before_stdout() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            let mut child = super::TokioCommand::new("sh")
                .arg("-c")
                // 256 KiB on one stderr line, then a stdout line.
                .arg("head -c 262144 /dev/zero | tr '\\0' x >&2; echo >&2; echo stdout-done")
                .stdout(super::Stdio::piped())
                .stderr(super::Stdio::piped())
                .spawn()
                .expect("sh");
            let mut rx = super::merged_lines(child.stdout.take(), child.stderr.take());
            let collect = async {
                let mut got = Vec::new();
                while let Some(line) = rx.recv().await {
                    got.push(line);
                }
                got
            };
            let got = tokio::time::timeout(std::time::Duration::from_secs(20), collect)
                .await
                .expect("deadlocked: stderr was not drained while stdout was read");
            let status = child.wait().await.unwrap();
            assert!(status.success());
            assert!(got.iter().any(|l| l == "stdout-done"), "stdout line missing");
            assert!(
                got.iter().any(|l| l.len() == 262144 && l.bytes().all(|b| b == b'x')),
                "the 256 KiB stderr line was not delivered whole"
            );
        });
    }

    /// The catalog every end-to-end driver gives its frontend
    /// (`shared/e2e/catalog.json`). It is written next to the recipe so
    /// `shared/e2e/check-recipe.py` can judge "an account exactly when the
    /// image needs one".
    const E2E_CATALOG: &str =
        include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/../../shared/e2e/catalog.json"));
    /// The leaf this frontend installs, picked through the catalog: the
    /// leaf of the default image's product that needs no account. GNOME,
    /// XFCE, KDE and Niri install the default image, which needs one, so the
    /// VM job boots both cases. The VM job installs the recipe with the
    /// leaf's image as it is (#322).
    fn e2e_leaf(catalog: &image_catalog::Catalog) -> &image_catalog::ImageLeaf {
        let default = &catalog.leaves[catalog.find(&catalog.default_image).expect("default_image")];
        catalog
            .leaves
            .iter()
            .find(|leaf| leaf.product == default.product && !leaf.needs_user_creation)
            .expect("the e2e catalog has a leaf of the default product with no account")
    }

    /// The leaf the end-to-end test installs needs no account, is not the
    /// default image (the other four frontends install that one), and is
    /// an image the VM job can boot as the recipe names it.
    #[test]
    fn e2e_leaf_is_the_canary_with_no_account() {
        let catalog = image_catalog::parse_manifest(E2E_CATALOG).unwrap();
        let leaf = e2e_leaf(&catalog);
        assert!(!leaf.needs_user_creation);
        assert_ne!(leaf.imgref, catalog.default_image);
        assert!(!leaf.composefs);
        assert_eq!(leaf.bootloader, "grub2");
    }

    /// End to end: the Install button's code path against the real backend.
    ///
    /// `stream_fisherman` is what `Message::StartInstall` performs: it
    /// resolves the wrapper (`offline::fisherman`: natively `bash -c
    /// 'pkexec /usr/local/bin/fisherman -; exit $?'`), pipes the recipe to
    /// its stdin and reads the progress protocol. In the end-to-end job
    /// shared/e2e/setup.sh has put the validating shim at that path and a
    /// pass-through pkexec first on PATH, so this exercises the real
    /// fisherman's Validate() on the recipe this crate serialises. The
    /// recipe is built the way the wizard builds it: a leaf of a catalog
    /// through `Recipe::apply_leaf`, the account through `user_block`.
    /// Ignored by default: it needs TUNA_E2E_DISK and the shim.
    ///
    ///     TUNA_E2E_DISK=/dev/loopN cargo test --release -- --ignored e2e
    #[test]
    #[ignore]
    fn e2e_install_path_reaches_fisherman() {
        let disk = std::env::var("TUNA_E2E_DISK").expect("TUNA_E2E_DISK (run shared/e2e/setup.sh)");
        let e2e_dir = std::env::var("TUNA_E2E_DIR").unwrap_or_else(|_| "/tmp/tuna-e2e".into());
        let catalog = image_catalog::parse_manifest(E2E_CATALOG).unwrap();
        std::fs::write(format!("{e2e_dir}/catalog.json"), E2E_CATALOG)
            .expect("the e2e directory is writable");
        let leaf = e2e_leaf(&catalog);
        let e2e_image = leaf.imgref.clone();

        let mut recipe = Recipe::default();
        recipe.disk = disk;
        recipe.apply_leaf(leaf, &model::Machine::default());
        recipe.hostname = "cosmic-e2e".into();
        // No account page: the catalog says the image makes its own first
        // user, through the same rule the page uses.
        assert!(!super::account_required_for(&catalog, None, "", Some(leaf)));

        // Drive the real stream and feed it through the real parser, which
        // is what the install page does. The old form called run_fisherman()
        // and matched a string in its returned log; that function no longer
        // exists, because collecting the output after the process exits is
        // precisely what stopped this frontend having a progress bar.
        let rt = tokio::runtime::Runtime::new().unwrap();
        let (code, log, fraction) = rt.block_on(async {
            use cosmic::iced::futures::StreamExt;
            let mut recipe = recipe;
            recipe.accept_experimental();
            let mut stream = Box::pin(TunaInstaller::stream_fisherman(
                serde_json::to_value(&recipe).unwrap(),
                Default::default(),
                false,
            ));
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
        assert_eq!(code, Some(0), "fisherman exit code");
        assert_eq!(super::install_outcome(code, false), super::Outcome::Succeeded);
        // Where the bar ended up, which is the property that was broken and
        // the one no string match could see: a frontend that does not parse
        // fisherman's protocol still reaches the Done page and still reports
        // success, and only the bar shows the difference.
        assert_eq!(
            fraction, 1.0,
            "the progress bar ended at {fraction}, not 1.0: the install page \
             is not parsing fisherman's progress protocol \
             (shared/progress/README.md)"
        );
        assert!(
            log.contains("Installation complete"),
            "the log carried no completion event"
        );
        let recorded = std::fs::read_to_string(format!("{e2e_dir}/recipe.json"))
            .expect("the shim recorded no recipe");
        let recorded: serde_json::Value = serde_json::from_str(&recorded).unwrap();
        assert!(recorded.get("user").is_none(), "an account for an image that needs none: {recorded}");
        assert_eq!(recorded["image"], e2e_image.as_str());
        assert_eq!(recorded["targetImgref"], recorded["image"]);
        assert_eq!(recorded["filesystem"], "xfs");
        // No list in the catalog for this leaf: no key, never `[]`, never
        // the catalog's `fallback_flatpaks` and never a list of this
        // frontend's own.
        assert!(recorded.get("flatpaks").is_none(), "{recorded}");
    }

    #[test]
    fn the_user_block_carries_the_account_and_the_shared_groups() {
        let mut recipe = Recipe::default();
        recipe.user = model::user_block("alex", "Alex Example", "s3cret", &model::default_groups());
        let json: serde_json::Value = serde_json::to_value(&recipe).unwrap();
        assert_eq!(
            json["user"],
            serde_json::json!({
                "username": "alex", "fullname": "Alex Example",
                "password": "s3cret",
                "groups": ["wheel", "sudo", "docker", "incus-admin", "libvirt", "dialout"],
            })
        );
        // An operator's list replaces it, an empty one included.
        let none = model::user_block("alex", "", "s3cret", &[]).unwrap();
        assert!(none.groups.is_empty());
        // The partial for validate has the username and never the password.
        let partial = super::partial_recipe(&recipe);
        assert_eq!(partial["user"], serde_json::json!({"username": "alex"}));
        assert!(!partial.to_string().contains("s3cret"));
        // And it round-trips.
        let restored: Recipe = serde_json::from_value(json).unwrap();
        assert_eq!(restored.user, recipe.user);
    }

    #[test]
    fn no_username_leaves_the_user_block_out() {
        assert_eq!(model::user_block("", "Alex Example", "s3cret", &model::default_groups()), None);
        let recipe = Recipe::default();
        let json: serde_json::Value = serde_json::to_value(&recipe).unwrap();
        assert!(json.get("user").is_none(), "{json}");
    }

    /// The account is required: no username, no password or a mismatched
    /// confirmation holds Continue.
    #[test]
    fn the_account_page_holds_continue_until_it_is_complete() {
        use super::account_complete;
        assert!(account_complete("alex", "s3cret", "s3cret"));
        assert!(!account_complete("", "s3cret", "s3cret"), "no username");
        assert!(!account_complete("alex", "", ""), "no password");
        assert!(!account_complete("alex", "s3cret", "s3cre"), "mismatch");
        assert!(!account_complete("alex", "s3cret", ""), "not confirmed");
    }

    /// fisherman's username problem holds the account page, not the options
    /// page; a hostname problem holds the options page, not the account page.
    #[test]
    fn each_page_is_held_only_by_its_own_fields() {
        use super::is_account_field;
        assert!(is_account_field("user.username"));
        assert!(is_account_field("user"));
        assert!(!is_account_field("hostname"));
        assert!(!is_account_field("username"));
        assert!(!is_account_field("encryption.passphrase"));
        let p = validate::Problem {
            field: "user.username".into(),
            code: "username_reserved".into(),
            message: "m".into(),
        };
        assert_eq!(p.render(), branding::get().text("validate_username_reserved"));
    }

    #[test]
    fn wizard_order_matches_gnome_parity() {
        let order = Page::ORDER;
        let at = |p: Page| order.iter().position(|q| *q == p).unwrap();
        // Preflight runs before the disk page; the tour runs after the
        // account and before the summary. No phone companion (#293).
        assert!(at(Page::Requirements) < at(Page::Welcome));
        assert!(at(Page::Welcome) < at(Page::Image));
        assert!(at(Page::Image) < at(Page::Language));
        assert!(at(Page::Language) < at(Page::Keyboard));
        assert!(at(Page::Keyboard) < at(Page::Timezone));
        assert!(at(Page::Timezone) < at(Page::Network));
        assert!(at(Page::Network) < at(Page::DiskSelect));
        assert!(at(Page::DiskSelect) < at(Page::Options));
        assert!(at(Page::Options) < at(Page::Account));
        assert!(at(Page::Account) < at(Page::Tour));
        assert!(at(Page::Tour) < at(Page::Confirm));
        assert!(at(Page::Confirm) < at(Page::Installing));
        assert!(at(Page::Installing) < at(Page::Done));
        assert_eq!(order.len(), 14);
        assert!(!order.iter().any(|p| p.slug() == "companion"));
    }

    fn two_leaf_catalog() -> image_catalog::Catalog {
        image_catalog::parse_manifest(
            r#"{"images": [
                {"name": "Needs", "imgref": "registry.example/os/needs:1",
                 "nvidia_imgref": "registry.example/os/needs-nvidia:1"},
                {"name": "Own", "imgref": "registry.example/os/own:1", "needs_user_creation": false}
            ]}"#,
        )
        .unwrap()
    }

    #[test]
    fn the_account_follows_the_image_on_record() {
        use super::account_required_for;
        let catalog = two_leaf_catalog();
        let (needs, own) = (&catalog.leaves[0], &catalog.leaves[1]);
        let empty = image_catalog::Catalog::default();
        // No catalog, no selection: required.
        assert!(account_required_for(&empty, None, "", None));
        // A leaf that sets nothing: required (the contract's default).
        assert!(account_required_for(&catalog, None, "", Some(needs)));
        // The image makes its own first user: skipped.
        assert!(!account_required_for(&catalog, None, "", Some(own)));
        // A custom reference the catalog does not have needs an account.
        // It used to skip the page, and nobody could sign in.
        assert!(account_required_for(&catalog, None, "ghcr.io/example/custom:latest", Some(own)));
        // A custom reference that IS a leaf takes that leaf's flag.
        assert!(!account_required_for(&catalog, None, " registry.example/os/own:1 ", Some(needs)));
        // Live media: the leaf of the booted image, whatever is selected.
        assert!(!account_required_for(&catalog, Some("registry.example/os/own:1"), "", Some(needs)));
        assert!(account_required_for(&catalog, Some("registry.example/os/needs-nvidia:1"), "", Some(own)));
        // A booted image the catalog does not have, or an unknown one.
        assert!(account_required_for(&catalog, Some("registry.example/os/other:1"), "", Some(own)));
        assert!(account_required_for(&catalog, Some(""), "", Some(own)));
    }

    /// `shared/catalog/fixtures/expected.json` `live_image`: on live media
    /// the account flag and the layout are those of the leaf of the booted
    /// image. The NVIDIA image of a leaf is that leaf.
    #[test]
    fn the_live_image_cases_are_the_shared_ones() {
        use super::account_required_for;
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../../shared/catalog/fixtures");
        let read = |name: &str| std::fs::read_to_string(format!("{dir}/{name}")).unwrap();
        let catalog = image_catalog::parse_manifest(&read("catalog.json")).unwrap();
        let expected: serde_json::Value = serde_json::from_str(&read("expected.json")).unwrap();
        let cases = expected["live_image"].as_array().unwrap();
        assert!(cases.len() >= 4);
        for case in cases {
            let live = case["live_image"].as_str().unwrap();
            let leaf = catalog.find(live).map(|i| catalog.leaves[i].imgref.clone());
            assert_eq!(leaf.as_deref(), case["leaf"].as_str(), "{live}: leaf");
            // Whatever row is selected, the booted image decides.
            for selected in [None, catalog.leaves.first(), catalog.leaves.last()] {
                assert_eq!(
                    account_required_for(&catalog, Some(live), "", selected),
                    case["needs_user_creation"].as_bool().unwrap(),
                    "{live}: needs_user_creation"
                );
            }
        }
    }

    /// fisherman exits 130 when cancelled; a signal ends the wrapper after
    /// this frontend signals its group. Neither is a failure (#299).
    #[test]
    fn a_cancel_is_not_a_failure() {
        use super::{install_outcome, Outcome};
        assert_eq!(install_outcome(Some(0), false), Outcome::Succeeded);
        assert_eq!(install_outcome(Some(0), true), Outcome::Succeeded, "it finished first");
        // 130 is fisherman's own word for "cancelled", whoever asked.
        assert_eq!(install_outcome(Some(130), false), Outcome::Cancelled);
        assert_eq!(install_outcome(Some(130), true), Outcome::Cancelled);
        // A signal after a confirmed cancel: SIGTERM to the wrapper's group.
        assert_eq!(install_outcome(None, true), Outcome::Cancelled);
        assert_eq!(install_outcome(Some(143), true), Outcome::Cancelled);
        // The same without a cancel is a crash.
        assert_eq!(install_outcome(None, false), Outcome::Failed);
        assert_eq!(install_outcome(Some(143), false), Outcome::Failed);
        // A real failure stays one, cancel or not.
        assert_eq!(install_outcome(Some(1), false), Outcome::Failed);
        assert_eq!(install_outcome(Some(1), true), Outcome::Failed);
        assert_eq!(install_outcome(Some(126), true), Outcome::Failed);
    }

    /// shared/progress/outcome-cases.json: the exit code decides, never a
    /// `complete` event (#269).
    #[test]
    fn the_shared_outcome_cases() {
        use super::{install_outcome, Outcome};
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../shared/progress/outcome-cases.json");
        let doc: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        let cases = doc["cases"].as_array().unwrap();
        assert!(cases.len() >= 10);
        for case in cases {
            let code = case["exit_code"].as_i64().map(|c| c as i32);
            let want = match case["outcome"].as_str().unwrap() {
                "succeeded" => Outcome::Succeeded,
                "cancelled" => Outcome::Cancelled,
                _ => Outcome::Failed,
            };
            let cancel = case["cancel_requested"] == serde_json::Value::Bool(true);
            assert_eq!(install_outcome(code, cancel), want, "{}", case["name"]);
        }
    }

    /// The cancel's whole path short of the UI: the wrapper's group is
    /// signalled, the wrapper ends by that signal, and the outcome is
    /// "cancelled".
    #[test]
    fn a_confirmed_cancel_signals_the_group_and_ends_cancelled() {
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            // A wrapper with a child, as bash has pkexec: both must go.
            let argv = ["bash", "-c", "sleep 30 & wait"].map(String::from);
            let mut child = super::spawn_wrapper(&argv, Vec::new()).await.expect("bash");
            let pid = child.id().unwrap();
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
            hardware::terminate_process_group(pid).unwrap();
            let status = tokio::time::timeout(std::time::Duration::from_secs(10), child.wait())
                .await
                .expect("the wrapper outlived the signal")
                .unwrap();
            assert_eq!(super::install_outcome(status.code(), true), super::Outcome::Cancelled);
            // Nothing of the group is left running. The child dies by the
            // same signal a moment after the wrapper, so look for a while.
            let mut left = String::new();
            for _ in 0..50 {
                let out = std::process::Command::new("pgrep")
                    .args(["-g", &pid.to_string()])
                    .output()
                    .unwrap();
                left = String::from_utf8_lossy(&out.stdout).into_owned();
                if left.is_empty() {
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            }
            assert!(left.is_empty(), "still in the group: {left}");
        });
    }

    #[test]
    fn recipe_roundtrip_and_field_serialization() {
        let mut recipe = Recipe::default();
        recipe.disk = "/dev/nvme0n1".into();
        recipe.filesystem = "btrfs".into();
        recipe.btrfs_subvolumes = true;
        recipe.target_imgref = "registry.example/os/atlas:stable".into();
        recipe.bootloader = "systemd".into();
        recipe.compose_fs_backend = true;
        recipe.flatpaks = Some(vec!["org.example.Browser".into()]);
        recipe.flatpak_var_path = "state/os/default/var".into();
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
        assert_eq!(restored.flatpak_var_path, recipe.flatpak_var_path);
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
        recipe.image = "registry.example/os/atlas:latest".into();

        let json_str = serde_json::to_string(&recipe).unwrap();
        let restored: Recipe = serde_json::from_str(&json_str).unwrap();
        assert_eq!(restored.image, "registry.example/os/atlas:latest");
    }
}
