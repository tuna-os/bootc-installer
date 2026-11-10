pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
utilsdir = join_paths(pkgdatadir, 'bootc_installer/utils')

sources = [
  '__init__.py',
  'finals.py',
  'icons.py',
  'run_async.py',
  'processor.py',
  'image_finals.py',
  'recipe.py',
  'builder.py',
  'codec_check.py',
  'phone_companion.py',
  'fisherman_runner.py',
  'fisherman_session.py',
  'field_check.py',
  'copy.py',
  'sha512crypt.py',
  'user_step.py',
  'i18n.py',
]

# The progress parser, the branding resolver, the account groups and the
# dry-run transcript are in the bootc_shared package
# (shared/python/meson.build).
install_data(sources, install_dir: utilsdir)
