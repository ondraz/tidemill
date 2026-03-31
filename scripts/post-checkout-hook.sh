#!/bin/sh
command -v git-lfs >/dev/null 2>&1 || { printf >&2 "\n%s\n\n" "This repository is configured for Git LFS but 'git-lfs' was not found on your path. If you no longer wish to use Git LFS, remove this hook by deleting the 'post-checkout' file in the hooks directory (set by 'core.hookspath'; usually '.git/hooks')."; exit 2; }
git lfs post-checkout "$@"

# --- Worktree setup ---
# When git worktree add runs, the previous HEAD ($1) is the null ref.
# We also verify we're actually in a worktree (not the main working tree)
# to avoid running this on initial clone.
prev_head="$1"
null_ref="0000000000000000000000000000000000000000"

if [ "$prev_head" = "$null_ref" ]; then
    git_dir=$(git rev-parse --git-dir)
    git_common_dir=$(git rev-parse --git-common-dir)

    # If git-dir and git-common-dir differ, we're in a worktree
    if [ "$git_dir" != "$git_common_dir" ]; then
        main_worktree=$(git -C "$git_common_dir" rev-parse --show-toplevel 2>/dev/null)
        new_worktree=$(pwd)

        if [ -z "$main_worktree" ]; then
            # Fallback: git-common-dir is typically <main>/.git
            main_worktree=$(dirname "$git_common_dir")
        fi

        printf "\n[post-checkout] Setting up new worktree: %s\n" "$new_worktree"
        printf "[post-checkout] Symlinking config files from: %s\n\n" "$main_worktree"

        # Discover .env files from main worktree via glob (.envrc is tracked in git)
        env_files=$(cd "$main_worktree" && for f in \
            .env .env-dev; do
            [ -f "$f" ] && printf '%s\n' "$f"
        done)

        # Symlink discovered env files plus static config files
        for f in \
            $env_files \
            subscriptions.code-workspace \
            .claude/settings.local.json; do
            src="$main_worktree/$f"
            if [ -f "$src" ]; then
                mkdir -p "$new_worktree/$(dirname "$f")"
                ln -sf "$src" "$new_worktree/$f"
                printf "  Linked %s\n" "$f"
            else
                printf "  Skipped %s (not found)\n" "$f"
            fi
        done

        # Run install and pre-commit setup
        if ! (cd "$new_worktree" && unset VIRTUAL_ENV && make install install-pre-commit); then
            printf >&2 "\n[post-checkout] WARNING: 'make install install-pre-commit' failed.\n"
            printf >&2 "[post-checkout] The worktree was created, but may not be fully configured.\n"
            printf >&2 "[post-checkout] To complete setup manually, run:\n"
            printf >&2 "    cd '%s' && unset VIRTUAL_ENV && make install install-pre-commit\n\n" "$new_worktree"
        else
            printf "\n[post-checkout] Worktree setup complete.\n"
        fi
    fi
fi
