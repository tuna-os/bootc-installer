//! Views, built from the cosmic widget set and the cosmic-theme palette.
//!
//! Nothing here hardcodes a colour or a pixel gap: colours come from
//! `cosmic::theme::active().cosmic()` and spacing from its `spacing` scale, so
//! the installer follows the user's COSMIC theme like every other COSMIC app.

use cosmic::iced::{Alignment, Length};
use cosmic::prelude::*;
use cosmic::widget;

use crate::{
    available_encryption_choices, branding, Message, Page, TunaInstaller, FILESYSTEMS,
};

/// Every user-facing string of the wizard, in one place.
///
/// The view functions below and [`page_text`] both read from here, so the
/// text the capture harness reports for a page is, by construction, the text
/// that page renders. `{product}` is substituted with [`branding::name`].
/// Lines a product may rebrand are branding copy keys (shared/branding),
/// read through [`t`] rather than constants here.
pub mod copy {
    pub const BACK: &str = "Back";
    pub const CONTINUE: &str = "Continue";

    pub const WELCOME_BODY: &str =
        "Welcome. This assistant will guide you through installing {product} onto this computer.";
    pub const WELCOME_CAPTION: &str = "You will choose a target disk and a few options. Nothing is \
         written to any disk until you confirm on the last step.";

    pub const DISK_TITLE: &str = "Select a disk";
    pub const DISK_SUBTITLE: &str = "Everything on the disk you pick will be erased.";
    pub const DISK_SCANNING: &str = "Scanning for disks\u{2026}";
    pub const DISK_UNKNOWN_MODEL: &str = "unknown model";
    pub const DISK_UNKNOWN_BUS: &str = "unknown bus";

    pub const OPTIONS_TITLE: &str = "Options";
    pub const OPTIONS_SUBTITLE: &str =
        "Sensible defaults are already chosen. Change them only if you need to.";
    pub const OPTIONS_SYSTEM: &str = "System";
    pub const OPTIONS_HOSTNAME: &str = "Computer name";
    pub const OPTIONS_FILESYSTEM: &str = "Filesystem";
    pub const OPTIONS_ENCRYPTION: &str = "Encryption";
    pub const OPTIONS_DISK_ENCRYPTION: &str = "Disk encryption";
    pub const OPTIONS_PASSPHRASE: &str = "Passphrase";
    pub const OPTIONS_PASSPHRASE_HINT: &str = "Required to unlock at boot";

    pub const CONFIRM_SUBTITLE: &str = "The last screen before anything is written.";
    pub const CONFIRM_SUMMARY: &str = "Summary";
    pub const CONFIRM_TARGET_DISK: &str = "Target disk";
    pub const CONFIRM_IMAGE: &str = "Image";
    pub const CONFIRM_LIVE_SUFFIX: &str = " (this system \u{2014} no download)";
    pub const INSTALLING_SUBTITLE: &str = "fisherman is writing the image to disk.";

    pub const DONE_FAIL_DETAIL: &str = "The install log above has the details.";
    pub const DONE_CLOSE: &str = "Close";
}

use copy::*;

/// A branding copy line (shared/branding/copy-defaults.json keys) with
/// `{name}` filled in.
fn t_line(key: &str) -> String {
    branding::text(key)
}

/// The same with `{disk}` filled in.
fn t_disk(key: &str, disk: &str) -> String {
    branding::get().text_with(key, &[("disk", disk)])
}

fn with_product(s: &str) -> String {
    s.replace("{product}", branding::name())
}

/// The strings the current page shows, in reading order.
///
/// This is what the capture harness writes to `texts.json` so the shared
/// parity report can match the COSMIC screens against the contract keywords
/// the way the GTK and Qt harnesses do from their widget trees. iced has no
/// widget-tree introspection, so the honest substitute is to render the pages
/// and their text from the same constants.
pub fn page_text(app: &TunaInstaller) -> Vec<String> {
    let recipe = app.recipe();
    match app.page() {
        Page::Welcome => {
            let mut t = vec![t_line("welcome_title"), with_product(WELCOME_BODY)];
            let sub = t_line("welcome_subtitle");
            if !sub.is_empty() {
                t.push(sub);
            }
            t.push(WELCOME_CAPTION.to_string());
            t.push(t_line("welcome_button"));
            t
        }
        Page::DiskSelect => {
            let mut t = vec![DISK_TITLE.to_string(), DISK_SUBTITLE.to_string()];
            if app.disks().is_empty() {
                t.push(DISK_SCANNING.to_string());
            }
            for disk in app.disks() {
                t.push(format!("/dev/{}", disk.name));
                t.push(disk_caption(disk));
            }
            t.push(BACK.to_string());
            if app.selected_disk().is_some() {
                t.push(CONTINUE.to_string());
            }
            t
        }
        Page::Options => {
            let choices = available_encryption_choices(app.has_tpm());
            let current = choices
                .iter()
                .find(|c| c.id == recipe.encryption.enc_type);
            let mut t = vec![
                OPTIONS_TITLE.to_string(),
                OPTIONS_SUBTITLE.to_string(),
                OPTIONS_SYSTEM.to_string(),
                OPTIONS_HOSTNAME.to_string(),
                recipe.hostname.clone(),
                OPTIONS_FILESYSTEM.to_string(),
                recipe.filesystem.clone(),
                OPTIONS_ENCRYPTION.to_string(),
                OPTIONS_DISK_ENCRYPTION.to_string(),
            ];
            if let Some(c) = current {
                t.push(c.label.to_string());
                t.push(c.description.to_string());
            }
            if recipe.encryption.enc_type.contains("passphrase") {
                t.push(OPTIONS_PASSPHRASE.to_string());
                t.push(OPTIONS_PASSPHRASE_HINT.to_string());
            }
            t.push(BACK.to_string());
            if app.encryption_ok() {
                t.push(CONTINUE.to_string());
            }
            t
        }
        Page::Confirm => vec![
            t_line("confirm_title"),
            confirm_subtitle(),
            t_disk("confirm_warning", &confirm_disk(app)),
            t_line("confirm_body"),
            CONFIRM_SUMMARY.to_string(),
            CONFIRM_TARGET_DISK.to_string(),
            confirm_disk(app),
            OPTIONS_FILESYSTEM.to_string(),
            recipe.filesystem.clone(),
            OPTIONS_ENCRYPTION.to_string(),
            recipe.encryption.enc_type.clone(),
            OPTIONS_HOSTNAME.to_string(),
            recipe.hostname.clone(),
            CONFIRM_IMAGE.to_string(),
            confirm_image(app),
            BACK.to_string(),
            t_line("confirm_button"),
        ],
        Page::Installing => vec![
            t_line("progress_title"),
            INSTALLING_SUBTITLE.to_string(),
            app.install_log().to_string(),
            t_line("progress_note"),
        ],
        Page::Done => {
            let (title, detail) = done_copy(app.install_ok());
            let mut t = vec![title, detail];
            if app.install_ok() {
                // The recovery panel, when there is a key (#129). The key
                // itself goes in too: the capture asserts on it, and a
                // panel drawn without it is the failure worth catching.
                if !app.progress.recovery_key.is_empty() {
                    t.push(t_line("recovery_key_title"));
                    t.push(t_line("recovery_key_body"));
                    t.push(app.progress.recovery_key.clone());
                    t.push(t_line("recovery_key_copy"));
                    t.push(t_line("recovery_key_ack"));
                }
                if !branding::get().store_url.is_empty() {
                    t.push(t_line("store_label"));
                }
                t.push(t_line("done_restart"));
            }
            t.push(DONE_CLOSE.to_string());
            t
        }
    }
}

fn disk_caption(disk: &crate::model::DiskInfo) -> String {
    format!(
        "{} \u{b7} {} \u{b7} {}",
        disk.size,
        if disk.model.is_empty() {
            DISK_UNKNOWN_MODEL
        } else {
            &disk.model
        },
        if disk.transport.is_empty() {
            DISK_UNKNOWN_BUS
        } else {
            &disk.transport
        },
    )
}

fn confirm_disk(app: &TunaInstaller) -> String {
    app.selected_disk()
        .and_then(|i| app.disks().get(i))
        .map_or_else(|| "?".to_string(), |d| format!("/dev/{}", d.name))
}

fn confirm_image(app: &TunaInstaller) -> String {
    match (app.live_image(), app.recipe().image.is_empty()) {
        (Some(live), true) => format!("{live}{CONFIRM_LIVE_SUFFIX}"),
        _ => app.recipe().image.clone(),
    }
}

fn done_copy(ok: bool) -> (String, String) {
    if ok {
        (t_line("done_title"), t_line("done_subtitle"))
    } else {
        (t_line("done_failed_title"), DONE_FAIL_DETAIL.to_string())
    }
}

/// The confirm subtitle: the product's own line (CONFIRM_SUBTITLE is the
/// neutral explanation, used when the branding sets none).
fn confirm_subtitle() -> String {
    let line = t_line("confirm_subtitle");
    if line.is_empty() {
        CONFIRM_SUBTITLE.to_string()
    } else {
        line
    }
}

pub fn view(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    // Deliberately renders nothing, so the capture harness's pixel gate can be
    // calibrated against a measured blank frame instead of a guessed one. This
    // is how the numbers in `capture.rs` were derived at the broken end, and
    // re-running it is how they should be re-derived if the UI changes:
    //
    //     TUNA_BLANK_SELFTEST=1 TUNA_CAPTURE_DIR=/tmp/blank just capture
    //
    // It must FAIL. If it ever passes, the gate has stopped detecting a page
    // that did not render, which is the entire point of the gate.
    if std::env::var_os("TUNA_BLANK_SELFTEST").is_some() {
        return widget::container(widget::space::horizontal())
            .width(Length::Fill)
            .height(Length::Fill)
            .into();
    }
    let content: Element<Message> = match app.page() {
        Page::Welcome => welcome(app),
        Page::DiskSelect => disk_select(app),
        Page::Options => options(app),
        Page::Confirm => confirm(app),
        Page::Installing => installing(app),
        Page::Done => done(app),
    };

    widget::container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .padding(spacing.space_l)
        .into()
}

/// Back / spacer / forward, the shape every COSMIC wizard uses.
fn nav_row<'a>(
    back: Option<Message>,
    forward: Option<(String, Message, bool)>,
) -> Element<'a, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let mut row = widget::row::with_capacity(3).spacing(spacing.space_s);

    if let Some(msg) = back {
        row = row.push(widget::button::standard(BACK).on_press(msg));
    }
    row = row.push(widget::space::horizontal());
    if let Some((label, msg, destructive)) = forward {
        let button = if destructive {
            widget::button::destructive(label)
        } else {
            widget::button::suggested(label)
        };
        row = row.push(button.on_press(msg));
    }
    row.align_y(Alignment::Center).into()
}

fn welcome(_app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let hero = widget::column::with_children(vec![
        widget::icon::from_name("drive-harddisk-symbolic")
            .size(64)
            .icon()
            .into(),
        widget::text::title1(t_line("welcome_title")).into(),
        widget::text::body(with_product(WELCOME_BODY)).into(),
    ]);
    let subtitle = t_line("welcome_subtitle");
    let hero = if subtitle.is_empty() {
        hero
    } else {
        hero.push(widget::text::body(subtitle))
    };
    let hero = hero
        .push(widget::text::caption(WELCOME_CAPTION))
        .spacing(spacing.space_s)
        .align_x(Alignment::Center)
        .width(Length::Fill);

    let next = t_line("welcome_button");
    widget::column::with_children(vec![
        widget::space::vertical().into(),
        hero.into(),
        widget::space::vertical().into(),
        nav_row(None, Some((next, Message::NextPage, false))),
    ])
    .spacing(spacing.space_m)
    .height(Length::Fill)
    .into()
}

fn disk_select(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let body: Element<Message> = if app.disks().is_empty() {
        widget::column::with_children(vec![
            widget::progress_bar::indeterminate_linear()
                .width(Length::Fill)
                .into(),
            widget::text::body(DISK_SCANNING).into(),
        ])
        .spacing(spacing.space_s)
        .into()
    } else {
        let mut list = widget::list_column().style(cosmic::theme::Container::List);
        for (i, disk) in app.disks().iter().enumerate() {
            let _selected = app.selected_disk() == Some(i);

            let label = widget::column::with_children(vec![
                widget::text::body(format!("/dev/{}", disk.name)).into(),
                widget::text::caption(disk_caption(disk)).into(),
            ])
            .spacing(spacing.space_xxxs)
            .width(Length::Fill);

            let row = widget::row::with_children(vec![
                label.into(),
                widget::radio(widget::text::body(""), i, app.selected_disk(), Message::SelectDisk)
                    .into(),
            ])
            .align_y(Alignment::Center)
            .spacing(spacing.space_s);

            list = list.add(
                widget::mouse_area(row)
                    .on_press(Message::SelectDisk(i)),
            );
        }
        widget::scrollable(list.into_element())
            .height(Length::Fill)
            .into()
    };

    page_frame(
        DISK_TITLE,
        DISK_SUBTITLE,
        body,
        nav_row(
            Some(Message::BackPage),
            app.selected_disk()
                .map(|_| (CONTINUE.to_string(), Message::NextPage, false)),
        ),
    )
}

fn options(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let recipe = app.recipe();

    let fs_index = FILESYSTEMS.iter().position(|f| *f == recipe.filesystem);

    // tunaOS#734: this list is `has_tpm`-filtered, same set XFCE offers on
    // this hardware, and `idx` below is a position in it — NOT in the full
    // `ENCRYPTION_CHOICES` table. `update()`'s `EncryptionChanged` handler
    // rebuilds the identical filtered list before indexing into it, so the
    // two stay in lockstep without passing the list through a message.
    let enc_choices = available_encryption_choices(app.has_tpm());
    let enc_index = enc_choices
        .iter()
        .position(|c| c.id == recipe.encryption.enc_type);
    let enc_labels: Vec<&str> = enc_choices.iter().map(|c| c.label).collect();
    let enc_description = enc_index
        .and_then(|i| enc_choices.get(i))
        .map(|c| c.description)
        .unwrap_or_default();
    // "luks-passphrase" and "tpm2-luks-passphrase" both contain this
    // substring; bare "tpm2-luks" and "none" don't. Same test `encryption_ok()`
    // uses to gate Continue below, so the field's presence and the field's
    // requiredness can never disagree.
    let needs_passphrase = recipe.encryption.enc_type.contains("passphrase");

    let system = widget::settings::section()
        .title(OPTIONS_SYSTEM)
        .add(widget::settings::item(
            OPTIONS_HOSTNAME,
            widget::text_input(branding::get().default_hostname.as_str(), &recipe.hostname)
                .on_input(Message::HostnameChanged)
                .width(Length::Fixed(260.0)),
        ))
        .add(widget::settings::item(
            OPTIONS_FILESYSTEM,
            widget::dropdown(&FILESYSTEMS, fs_index, Message::FilesystemChanged),
        ));

    let mut security = widget::settings::section().title(OPTIONS_ENCRYPTION).add(
        widget::settings::item::builder(OPTIONS_DISK_ENCRYPTION)
            .description(enc_description)
            // Handed over by value, not as `.as_slice()`: the returned
            // `Element` outlives this function, so a borrow of the local
            // `Vec` would not compile (E0515). `Vec<&'static str>` converts
            // into an owned `Cow<[&str]>`, which the dropdown keeps.
            .control(widget::dropdown(
                enc_labels,
                enc_index,
                Message::EncryptionChanged,
            )),
    );

    // Only build the passphrase controls once the chosen encryption actually
    // carries one. The KDE sibling crashed precisely at this kind of
    // conditional: its constructor called setChecked() before the passphrase
    // widgets existed, so the toggled handler ran against uninitialised
    // pointers. In Rust the equivalent mistake cannot compile, but the
    // conditional is still the honest UI — and "tpm2-luks" alone must NOT show
    // this field, since fisherman never reads a passphrase for it.
    if needs_passphrase {
        security = security.add(widget::settings::item(
            OPTIONS_PASSPHRASE,
            widget::secure_input(
                OPTIONS_PASSPHRASE_HINT,
                &recipe.encryption.passphrase,
                Some(Message::TogglePassphraseVisible),
                app.passphrase_hidden(),
            )
            .on_input(Message::PassphraseChanged)
            .width(Length::Fixed(260.0)),
        ));
    }

    let body = widget::scrollable(
        widget::settings::view_column(vec![system.into(), security.into()])
            .spacing(spacing.space_m),
    )
    .height(Length::Fill);

    page_frame(
        OPTIONS_TITLE,
        OPTIONS_SUBTITLE,
        body.into(),
        nav_row(
            Some(Message::BackPage),
            // Blocked while a passphrase-carrying choice has an empty
            // passphrase, so this can never reach Confirm/Install and only
            // then discover fisherman rejects the recipe (tunaOS#734).
            app.encryption_ok()
                .then_some((CONTINUE.to_string(), Message::NextPage, false)),
        ),
    )
}

fn confirm(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let recipe = app.recipe();

    let disk = confirm_disk(app);
    let image = confirm_image(app);

    let summary = widget::settings::section()
        .title(CONFIRM_SUMMARY)
        .add(widget::settings::item(CONFIRM_TARGET_DISK, widget::text::body(disk)))
        .add(widget::settings::item(
            OPTIONS_FILESYSTEM,
            widget::text::body(recipe.filesystem.clone()),
        ))
        .add(widget::settings::item(
            OPTIONS_ENCRYPTION,
            widget::text::body(recipe.encryption.enc_type.clone()),
        ))
        .add(widget::settings::item(
            OPTIONS_HOSTNAME,
            widget::text::body(recipe.hostname.clone()),
        ))
        .add(widget::settings::item(CONFIRM_IMAGE, widget::text::body(image)));

    // Not `widget::warning::warning`: its filled amber background renders the
    // body text near-invisible on the dark COSMIC palette, which the first
    // screenshot run made obvious and no diff ever would have. A card with
    // warning-coloured text keeps the emphasis and stays legible in both
    // light and dark.
    let theme = cosmic::theme::active();
    let warning = widget::container(
        widget::row::with_children(vec![
            widget::icon::from_name("dialog-warning-symbolic")
                .size(16)
                .icon()
                .into(),
            widget::text::body(t_disk("confirm_warning", &confirm_disk(app)))
            .class(cosmic::theme::Text::Color(
                theme.cosmic().warning_text_color().into(),
            ))
            .into(),
        ])
        .spacing(spacing.space_xs)
        .align_y(Alignment::Center),
    )
    .class(cosmic::theme::Container::Card)
    .padding(spacing.space_s)
    .width(Length::Fill);

    let mut parts = vec![warning.into(), summary.into()];
    let tagline = t_line("confirm_body");
    if !tagline.is_empty() {
        parts.push(widget::text::body(tagline).into());
    }
    let body = widget::scrollable(
        widget::column::with_children(parts).spacing(spacing.space_m),
    )
    .height(Length::Fill);

    page_frame(
        t_line("confirm_title"),
        confirm_subtitle(),
        body.into(),
        nav_row(
            Some(Message::BackPage),
            Some((t_line("confirm_button"), Message::StartInstall, true)),
        ),
    )
}

fn installing(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let theme = cosmic::theme::active();
    let cosmic_theme = theme.cosmic();

    let log = widget::container(
        widget::scrollable(
            widget::text::monotext(app.install_log())
                .size(12)
                .width(Length::Fill),
        )
        .height(Length::Fill),
    )
    .class(cosmic::theme::Container::Card)
    .padding(spacing.space_s)
    .width(Length::Fill)
    .height(Length::Fill);

    // The install's real position, from fisherman's protocol
    // (shared/progress/README.md). This was indeterminate_linear() for the
    // whole install — docs/PARITY.md gap #2 — which told the user only that
    // something was happening, for the twenty minutes it takes.
    //
    // Indeterminate is kept for the window before the first event lands, so
    // the page never looks stalled while fisherman starts up; that is the one
    // moment when "something is happening" really is all that is known.
    let progress = app.progress();
    let bar: Element<'_, Message> = if progress.started() {
        widget::progress_bar::determinate_linear(progress.fraction)
            .width(Length::Fill)
            .into()
    } else {
        widget::progress_bar::indeterminate_linear()
            .width(Length::Fill)
            .into()
    };

    let mut children: Vec<Element<'_, Message>> = vec![bar];
    if progress.started() {
        // "Step 5 of 8 — Installing <product>…". The count comes from the
        // event, never a constant: fisherman computes total_steps from the
        // recipe.
        children.push(
            widget::text::caption(format!(
                "Step {} of {} — {}",
                progress.step, progress.total_steps, progress.step_name
            ))
            .into(),
        );
    }

    let body = widget::column::with_children({
        children.extend(vec![
        log.into(),
        widget::text::caption(t_line("progress_note"))
            .class(cosmic::theme::Text::Color(cosmic_theme.warning_text_color().into()))
            .into(),
        ]);
        children
    })
    .spacing(spacing.space_s)
    .height(Length::Fill);

    page_frame(
        t_line("progress_title"),
        INSTALLING_SUBTITLE,
        body.into(),
        widget::space::horizontal().into(),
    )
}

fn done(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let theme = cosmic::theme::active();
    let cosmic_theme = theme.cosmic();

    let (title, detail) = done_copy(app.install_ok());
    let (icon, colour) = if app.install_ok() {
        ("emblem-ok-symbolic", cosmic_theme.success_text_color())
    } else {
        ("dialog-error-symbolic", cosmic_theme.destructive_text_color())
    };

    let mut hero = widget::column::with_children(vec![
        widget::icon::from_name(icon).size(64).icon().into(),
        widget::text::title2(title)
            .class(cosmic::theme::Text::Color(colour.into()))
            .into(),
        widget::text::body(detail).into(),
    ]);
    // store_label -> store_url on every frontend when the branding sets a
    // store (docs/PARITY.md).
    let store_url = branding::get().store_url.clone();
    if app.install_ok() && !store_url.is_empty() {
        hero = hero.push(
            widget::button::link(t_line("store_label")).on_press(Message::OpenUrl(store_url)),
        );
    }
    let hero = hero
        .spacing(spacing.space_s)
        .align_x(Alignment::Center)
        .width(Length::Fill);

    // The recovery key (#129). fisherman emits it once, after TPM enrolment,
    // and for a tpm2-luks install it is the only way back into the disk if
    // the TPM state changes. It used to go to the log pane and nowhere else:
    // the log scrolls, nothing pauses, and a user could reach this page and
    // restart having never seen it.
    //
    // A panel rather than a dialog, for the same reason XFCE uses one: a
    // dialog is dismissed and then the key is gone, while this stays on
    // screen for as long as it takes to write down.
    let key = app.progress.recovery_key.clone();
    let show_recovery = app.install_ok() && !key.is_empty();
    let recovery: Option<Element<'_, Message>> = show_recovery.then(|| {
        widget::column::with_children(vec![
            widget::text::title4(t_line("recovery_key_title")).into(),
            widget::text::body(t_line("recovery_key_body")).into(),
            widget::text::monotext(key.clone()).into(),
            widget::button::standard(t_line("recovery_key_copy"))
                .on_press(Message::CopyRecoveryKey)
                .into(),
            widget::checkbox(app.recovery_ack)
                .label(t_line("recovery_key_ack"))
                .on_toggle(Message::RecoveryAckToggled)
                .into(),
        ])
        .spacing(spacing.space_xs)
        .align_x(Alignment::Center)
        .width(Length::Fill)
        .into()
    });

    // Restart is the primary action after a successful install (the same
    // as the other frontends); Close stays available either way.
    //
    // While a recovery key is on screen it stays dead until the box is
    // ticked: leaving this page is what ends the chance to read the key. An
    // iced button with no on_press IS the disabled state.
    let restart_ready = !app.recovery_key_pending();
    let actions: Element<'_, Message> = if app.install_ok() {
        let mut restart = widget::button::suggested(t_line("done_restart"));
        if restart_ready {
            restart = restart.on_press(Message::Reboot);
        }
        widget::row::with_children(vec![
            widget::space::horizontal().into(),
            widget::button::standard(DONE_CLOSE)
                .on_press(Message::Quit)
                .into(),
            restart.into(),
        ])
        .spacing(spacing.space_s)
        .into()
    } else {
        nav_row(None, Some((DONE_CLOSE.to_string(), Message::Quit, false)))
    };

    let mut children: Vec<Element<'_, Message>> = vec![
        widget::space::vertical().into(),
        hero.into(),
    ];
    if let Some(panel) = recovery {
        children.push(panel);
    }
    children.push(widget::space::vertical().into());
    children.push(actions);

    widget::column::with_children(children)
        .spacing(spacing.space_m)
        .height(Length::Fill)
        .into()
}

/// Title, subtitle, scrolling body, navigation footer.
fn page_frame<'a>(
    title: impl Into<std::borrow::Cow<'a, str>> + 'a,
    subtitle: impl Into<std::borrow::Cow<'a, str>> + 'a,
    body: Element<'a, Message>,
    footer: Element<'a, Message>,
) -> Element<'a, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    widget::column::with_children(vec![
        widget::text::title2(title).into(),
        widget::text::caption(subtitle).into(),
        widget::divider::horizontal::default().into(),
        body,
        widget::divider::horizontal::default().into(),
        footer,
    ])
    .spacing(spacing.space_s)
    .height(Length::Fill)
    .into()
}
