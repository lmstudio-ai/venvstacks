Added
-----

- `show` :ref:`subcommand <command-show>` to display layer definitions (added in :issue:`159`).
- `--show` :ref:`option <option-show>` on subcommands (other than `show`) to display the selected
  layers and operations before executing the command (added in :issue:`159`).
- `--show-only` :ref:`option <option-show-only>` on subcommands (other than `show`) to display the
  selected layers and operations *without* executing the command (added in :issue:`159`).
- `--json` :ref:`option <option-json>` on subcommands to display the selected layers
  and operations as JSON rather than as a human-readable tree. For commands other than `show`,
  implies `--show-only` if `--show` is not pass explicitly (added in :issue:`159`).
