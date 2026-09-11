# Repository Maintenance

Read this guidance before modifying the repository's `Makefile`.

## Command-only Make targets

When a change adds or renames a Make target, determine whether its recipe creates
a file or directory whose path is the target name. If it does not, the target is
command-only and must be added to the `Makefile`'s `.PHONY` declaration in the
same change.

Keep the `.PHONY` declaration synchronized when command-only targets are renamed
or removed. Do not declare a file-producing target phony unless the recipe is
intentionally required to run on every invocation.
