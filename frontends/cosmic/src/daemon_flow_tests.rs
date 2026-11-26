//! The wizard on the daemon backend, driven through `update()`.
//!
//! `fishermand_mock_tests` calls the client functions. These tests build
//! the application and send it the messages that the pages send, in page
//! order, against the mock daemon. Each task that `update()` returns runs
//! to its end, and its messages go back into `update()`, as the runtime
//! does. They found what the client tests cannot: a page that never
//! releases Continue, an Install that a skipped page still holds, and an
//! install page that nothing leaves.
//!
//! They need `FISHERMAND_BIN`, like `fishermand_mock_tests`. Without it
//! each test prints `SKIPPED` once and returns.

use std::collections::VecDeque;
use std::sync::{Mutex, MutexGuard};

use cosmic::app::Core;
use cosmic::iced::futures::StreamExt;

use crate::fishermand::test_seam;
use crate::fishermand_mock_tests::Mock;
use crate::{Flags, Message, Page, TunaInstaller};

/// One test at a time: the backend and the socket directory are set for
/// the whole process (`test_seam`).
static ONE_AT_A_TIME: Mutex<()> = Mutex::new(());

struct Wizard {
    app: TunaInstaller,
    runtime: tokio::runtime::Runtime,
    _mock: Mock,
    _lock: MutexGuard<'static, ()>,
}

impl Drop for Wizard {
    fn drop(&mut self) {
        *test_seam::DAEMON.lock().unwrap() = None;
        *test_seam::SOCKET_DIR.lock().unwrap() = None;
    }
}

impl Wizard {
    /// The application on the mock for `scenario`, after its start-up
    /// tasks (the probe) ran. `None` when there is no mock binary.
    fn start(scenario: &str) -> Option<Self> {
        let lock = ONE_AT_A_TIME.lock().unwrap_or_else(|e| e.into_inner());
        let mock = Mock::start(scenario)?;
        *test_seam::DAEMON.lock().unwrap() = Some(true);
        *test_seam::SOCKET_DIR.lock().unwrap() = Some(mock.dir.to_string_lossy().into_owned());
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .unwrap();
        let (mut app, task) = {
            let _guard = runtime.enter();
            <TunaInstaller as cosmic::Application>::init(Core::default(), Flags { capture: None })
        };
        // The tests say who makes the user; the environment does not.
        app.firstboot_owns_user = false;
        let mut wizard = Self { app, runtime, _mock: mock, _lock: lock };
        wizard.run(task);
        Some(wizard)
    }

    /// Sends one message and everything that follows from it.
    fn send(&mut self, message: Message) {
        let task = {
            let _guard = self.runtime.enter();
            cosmic::Application::update(&mut self.app, message)
        };
        self.run(task);
    }

    /// Runs a task to its end. Each application message that it yields
    /// goes into `update()`, and that task runs too.
    fn run(&mut self, task: cosmic::app::Task<Message>) {
        let mut tasks = VecDeque::from([task]);
        while let Some(task) = tasks.pop_front() {
            let Some(mut stream) = cosmic::iced::runtime::task::into_stream(task) else {
                continue;
            };
            let mut messages = Vec::new();
            self.runtime.block_on(async {
                let end = tokio::time::sleep(std::time::Duration::from_secs(60));
                tokio::pin!(end);
                loop {
                    tokio::select! {
                        action = stream.next() => match action {
                            Some(cosmic::iced::runtime::Action::Output(cosmic::Action::App(m))) => messages.push(m),
                            Some(_) => {}
                            None => break,
                        },
                        () = &mut end => panic!("a task did not end in 60 s"),
                    }
                }
            });
            for message in messages {
                let next = {
                    let _guard = self.runtime.enter();
                    cosmic::Application::update(&mut self.app, message)
                };
                tasks.push_back(next);
            }
        }
    }

    /// Presses Continue until the wizard is on `page`. Fails when a page
    /// on the way is not the one before `page` in the walk.
    fn continue_to(&mut self, page: Page) -> Vec<Page> {
        let mut seen = vec![self.app.page()];
        while self.app.page() != page {
            let before = self.app.page();
            self.send(Message::NextPage);
            assert_ne!(self.app.page(), before, "Continue did not leave {before:?}; walked {seen:?}");
            seen.push(self.app.page());
            assert!(seen.len() < 30, "never reached {page:?}: {seen:?}");
        }
        seen
    }

    fn fill_account(&mut self) {
        for message in [
            Message::UsernameChanged("alex".into()),
            Message::PasswordChanged("tr0ub4dor and 3".into()),
            Message::PasswordConfirmChanged("tr0ub4dor and 3".into()),
        ] {
            self.send(message);
        }
    }

    /// What the confirm page's Install button needs.
    fn install_is_live(&self) -> bool {
        !self.app.source_blocked() && self.app.confirm_problems().is_empty()
    }
}

macro_rules! wizard_or_skip {
    ($scenario:expr) => {
        match Wizard::start($scenario) {
            Some(wizard) => wizard,
            None => return,
        }
    };
}

#[test]
fn flow_no_tpm_walks_every_page_to_done() {
    let mut w = wizard_or_skip!("existing-data,no-tpm");
    // Live media: no image page and no network page. No RST, no EULA.
    assert_eq!(w.app.page(), Page::TryOrInstall);
    let seen = w.continue_to(Page::Encryption);
    assert_eq!(
        seen,
        [
            Page::TryOrInstall,
            Page::Language,
            Page::Keyboard,
            Page::Timezone,
            Page::DiskSelect,
            Page::WipeOrFree,
            Page::Encryption,
        ]
    );
    // The location switch: untouched is no choice, moved is a choice.
    assert_eq!(w.app.location_choice(), None);
    w.send(Message::LocationServicesToggled(true));
    assert_eq!(w.app.location_choice(), Some(true));

    // The daemon installs encrypted only: the page offers no unencrypted
    // type, and its one row is the passphrase type.
    assert_eq!(crate::encryption_choices_for(w.app.has_tpm(), true), ["luks-passphrase"]);
    w.send(Message::EncryptionChanged(0));
    assert_eq!(w.app.recipe().encryption.enc_type, "luks-passphrase");
    w.send(Message::EncryptionChanged(1));
    assert_eq!(w.app.recipe().encryption.enc_type, "luks-passphrase");

    // No TPM: the page asks for a passphrase, and holds Continue until
    // the daemon accepts one that was typed the same twice.
    assert_eq!(w.app.recipe().encryption.enc_type, "luks-passphrase");
    assert!(!w.app.encryption_page_ok(), "an empty passphrase passed");
    w.send(Message::PassphraseChanged("correct horse battery".into()));
    assert!(!w.app.encryption_page_ok(), "an unconfirmed passphrase passed");
    w.send(Message::PassphraseConfirmChanged("correct horse battery".into()));
    assert!(
        w.app.encryption_page_ok(),
        "Continue stays off after a valid passphrase: {:?}",
        w.app.problem("encryption").map(|p| p.render())
    );

    w.continue_to(Page::Account);
    assert!(!w.app.account_ok());
    w.fill_account();
    assert!(w.app.account_ok());

    w.continue_to(Page::Confirm);
    assert!(w.app.keeps_data(), "free space is the default of the existing-data page");
    assert!(w.install_is_live(), "{:?}", w.app.confirm_problems().iter().map(|p| p.render()).collect::<Vec<_>>());

    // Install: the page leaves on the terminal event, and the page after
    // it asks the daemon for the key.
    w.send(Message::StartInstall);
    assert_eq!(w.app.page(), Page::RecoveryKey);
    assert!(w.app.install_ok());
    assert!(
        crate::fishermand::is_recovery_key_shape(&w.app.progress.recovery_key),
        "the recovery-key page has no key: {:?}",
        w.app.recovery_error()
    );
    // Done is off until the box is ticked; then it enrols and leaves.
    w.send(Message::RecoveryAckToggled(true));
    w.send(Message::RecoveryDone);
    assert_eq!(w.app.page(), Page::Handoff, "{:?}", w.app.recovery_error());
    assert_eq!(w.app.handoff_mode(), "reboot");
    w.send(Message::HandoffContinue);
    assert_eq!(w.app.page(), Page::Done, "{:?}", w.app.handoff_error());
    assert!(w.app.install_ok());
}

#[test]
fn flow_first_boot_tool_skips_the_account_and_install_is_still_live() {
    let mut w = wizard_or_skip!("happy");
    w.app.firstboot_owns_user = true;
    let seen = w.continue_to(Page::Confirm);
    // A TPM: no encryption page. The tool: no account page.
    assert!(!seen.contains(&Page::Encryption), "{seen:?}");
    assert!(!seen.contains(&Page::Account), "{seen:?}");
    assert_eq!(w.app.recipe().encryption.enc_type, "tpm2-luks");
    assert!(w.app.username().is_empty());
    // No account does not hold Install.
    assert!(w.install_is_live(), "{:?}", w.app.confirm_problems().iter().map(|p| p.render()).collect::<Vec<_>>());
    w.send(Message::StartInstall);
    assert_eq!(w.app.page(), Page::RecoveryKey);
    assert!(w.app.install_ok());
}

#[test]
fn flow_without_the_first_boot_tool_the_account_page_shows() {
    let mut w = wizard_or_skip!("happy");
    let seen = w.continue_to(Page::Account);
    assert!(seen.contains(&Page::Account));
    // The page holds Continue until the account is there.
    assert!(!w.app.account_ok());
}

#[test]
fn flow_an_install_that_fails_in_its_first_steps_leaves_the_install_page() {
    let mut w = wizard_or_skip!("repart-error");
    w.app.firstboot_owns_user = true;
    w.continue_to(Page::Confirm);
    w.send(Message::StartInstall);
    assert_eq!(w.app.page(), Page::Done);
    assert!(!w.app.install_ok());
    assert!(!w.app.install_cancelled());
    assert_eq!(w.app.daemon_failure(), Some("repart_failed"));
    // Try again goes back to Confirm.
    w.send(Message::TryAgain);
    assert_eq!(w.app.page(), Page::Confirm);
}

#[test]
fn flow_a_refused_choice_leaves_the_install_page() {
    // ConfigureTarget refuses the locale before any disk step.
    let mut w = wizard_or_skip!("happy");
    w.app.firstboot_owns_user = true;
    w.continue_to(Page::Confirm);
    w.app.recipe.locale = "not a locale!".into();
    w.send(Message::StartInstall);
    assert_eq!(w.app.page(), Page::Done);
    assert!(!w.app.install_ok());
    assert_eq!(w.app.daemon_failure(), Some("locale_invalid"));
}

#[test]
fn flow_a_daemon_that_went_away_leaves_the_install_page() {
    let mut w = wizard_or_skip!("happy");
    w.app.firstboot_owns_user = true;
    w.continue_to(Page::Confirm);
    assert!(w.install_is_live());
    // The daemon goes away between Confirm and the Install click.
    *test_seam::SOCKET_DIR.lock().unwrap() = Some("/nonexistent/fishermand".into());
    w.send(Message::StartInstall);
    assert_eq!(w.app.page(), Page::Done);
    assert!(!w.app.install_ok());
    assert_eq!(w.app.daemon_failure(), Some("daemon_unreachable"));
    // Back on Confirm, the daemon still does not answer: Install is held.
    w.send(Message::TryAgain);
    assert_eq!(w.app.page(), Page::Confirm);
    assert!(!w.install_is_live());
}

#[test]
fn flow_cancel_ends_on_the_cancelled_page() {
    let mut w = wizard_or_skip!("cancel");
    w.app.firstboot_owns_user = true;
    w.continue_to(Page::Confirm);
    // The mock waits in install_os until Cancel comes. The install task
    // runs on its own thread here, so that the cancel can go beside it.
    let task = {
        let _guard = w.runtime.enter();
        cosmic::Application::update(&mut w.app, Message::StartInstall)
    };
    assert_eq!(w.app.page(), Page::Installing);
    let dir = w._mock.dir.clone();
    let canceller = std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(2));
        let mut conn = crate::fishermand::Connection::connect(dir.join("io.tunaos.Fisherman")).unwrap();
        crate::fishermand::cancel(&mut conn).unwrap()
    });
    // What ConfirmCancelInstall sets before it sends Cancel.
    w.app.cancel_confirmed = true;
    w.run(task);
    assert_eq!(canceller.join().unwrap()["wasInstalling"], serde_json::Value::Bool(true));
    assert_eq!(w.app.page(), Page::Done);
    assert!(w.app.install_cancelled());
    assert!(!w.app.install_ok());
}

#[test]
fn flow_a_forced_erase_holds_install_for_three_seconds() {
    // tight-space: data and no free space. No choice was offered, so the
    // confirm page counts down before Install is live.
    let mut w = wizard_or_skip!("tight-space");
    w.app.firstboot_owns_user = true;
    let seen = w.continue_to(Page::DiskSelect);
    assert!(!seen.contains(&Page::WipeOrFree));
    assert!(w.app.forced_erase());
    // Open the confirm page, and hold its tasks: the countdown is one.
    let started = std::time::Instant::now();
    let task = {
        let _guard = w.runtime.enter();
        cosmic::Application::update(&mut w.app, Message::NextPage)
    };
    assert_eq!(w.app.page(), Page::Confirm);
    assert_eq!(w.app.erase_countdown(), crate::ERASE_COUNTDOWN_SECONDS);
    assert_eq!(crate::ERASE_COUNTDOWN_SECONDS, 3);
    // Install does nothing while the countdown runs.
    w.send(Message::StartInstall);
    assert_eq!(w.app.page(), Page::Confirm);
    assert!(!w.app.installing);
    // A tick of an older visit counts nothing.
    w.send(Message::EraseCountdownTick(w.app.countdown_seq - 1));
    assert_eq!(w.app.erase_countdown(), 3);
    // The countdown runs out in three seconds, not before.
    w.run(task);
    assert_eq!(w.app.erase_countdown(), 0);
    assert!(started.elapsed() >= std::time::Duration::from_secs(3), "{:?}", started.elapsed());
    assert!(w.install_is_live());
    assert_eq!(w.app.install_mode(), crate::InstallMode::Erase);
    w.send(Message::StartInstall);
    assert!(w.app.install_ok());
}

#[test]
fn flow_a_disk_that_keeps_its_data_has_no_countdown() {
    let mut w = wizard_or_skip!("existing-data");
    w.app.firstboot_owns_user = true;
    w.continue_to(Page::Confirm);
    assert!(w.app.keeps_data());
    assert_eq!(w.app.erase_countdown(), 0);
    let mut w = wizard_or_skip_second(w, "happy");
    w.app.firstboot_owns_user = true;
    w.continue_to(Page::Confirm);
    assert!(!w.app.forced_erase(), "an empty disk is not a forced erase");
    assert_eq!(w.app.erase_countdown(), 0);
}

/// Ends `first` (its lock, its mock) and starts a wizard on `scenario`.
fn wizard_or_skip_second(first: Wizard, scenario: &str) -> Wizard {
    drop(first);
    Wizard::start(scenario).expect("the mock binary was there for the first wizard")
}

#[test]
fn flow_off_the_medium_an_image_to_download_shows_the_network_page() {
    // not-live: an installed system, no live image. An image that the
    // install downloads needs the network page after the time zone (the
    // walkthrough's offline run).
    let mut w = wizard_or_skip!("not-live");
    assert!(w.app.live_image().is_none());
    assert!(w.app.page_visible(Page::Network));
    let seen = w.continue_to(Page::DiskSelect);
    let at = |p: Page| seen.iter().position(|s| *s == p).unwrap_or_else(|| panic!("{p:?} not in {seen:?}"));
    assert_eq!(at(Page::Network), at(Page::Timezone) + 1, "{seen:?}");
}
