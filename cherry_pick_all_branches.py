#!/usr/bin/env python3
"""Cross-platform tool to cherry-pick the last commit(s) to all branches.

Key behaviors:
- Pauses on conflicts and resumes after resolution.
- If PDF conflicts are detected (common for generated LaTeX outputs), the script will
  try to regenerate the PDF(s) from their matching .tex first and open them for review.

Usage:
    python cherry_pick_all_branches.py [--exclude-branch PATTERN] [--state-file FILE] [-n N]

    --exclude-branch supports wildcards: exp/*, */de/*, feature/*
"""

import subprocess
import sys
import os
import json
import argparse
import fnmatch
import platform
from pathlib import Path


def run_git_command(cmd, check=True):
    """Run a git command and return the result (stdout, stderr, success)."""
    try:
        result = subprocess.run(
            ['git'] + cmd,
            capture_output=True,
            text=True,
            check=check
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode == 0
    except subprocess.CalledProcessError as e:
        stdout = e.stdout.strip() if e.stdout else ""
        stderr = e.stderr.strip() if e.stderr else ""
        return stdout, stderr, False
    except FileNotFoundError:
        print("Error: git command not found. Please ensure git is installed and in PATH.")
        sys.exit(1)


def run_command(cmd, cwd=None, check=True):
    """Run a non-git command and return (stdout, stderr, success)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            cwd=str(cwd) if cwd else None
        )
        return (result.stdout or "").strip(), (result.stderr or "").strip(), result.returncode == 0
    except subprocess.CalledProcessError as e:
        stdout = (e.stdout or "").strip()
        stderr = (e.stderr or "").strip()
        return stdout, stderr, False
    except FileNotFoundError:
        return "", f"Command not found: {cmd[0]}", False


def get_current_branch():
    """Get the current branch name."""
    output, _, success = run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'])
    return output if success else None


def get_last_commit_hash():
    """Get the hash of the last commit."""
    output, _, success = run_git_command(['rev-parse', 'HEAD'])
    if not success:
        print("Error: Could not get last commit hash.")
        sys.exit(1)
    return output


def get_last_n_commits(n):
    """Get the last n commits with their hashes and descriptions."""
    if n <= 0:
        return []

    # Get commit hashes (oldest to newest)
    output, _, success = run_git_command(['log', '--reverse', '-n', str(n), '--format=%H'])
    if not success:
        print("Error: Could not get commit list.")
        sys.exit(1)

    commit_hashes = [h.strip() for h in output.split('\n') if h.strip()]

    # Get commit details (hash, subject, body)
    commits = []
    for commit_hash in commit_hashes:
        subject_output, _, _ = run_git_command(['log', '-1', '--format=%s', commit_hash])
        subject = subject_output.strip()

        body_output, _, _ = run_git_command(['log', '-1', '--format=%b', commit_hash])
        body = body_output.strip()

        commits.append({
            'hash': commit_hash,
            'subject': subject,
            'body': body
        })

    return commits


def get_all_branches(exclude_current=True, exclude_patterns=None):
    """Get all local branches."""
    if exclude_patterns is None:
        exclude_patterns = []

    output, _, success = run_git_command(['branch', '--format=%(refname:short)'])
    if not success:
        print("Error: Could not get list of branches.")
        sys.exit(1)

    branches = [b.strip() for b in output.split('\n') if b.strip()]
    current = get_current_branch()

    if exclude_current and current:
        branches = [b for b in branches if b != current]

    for pattern in exclude_patterns:
        # Use pattern matching if pattern contains wildcards, otherwise exact match
        if '*' in pattern or '?' in pattern or '[' in pattern:
            branches = [b for b in branches if not fnmatch.fnmatch(b, pattern)]
        else:
            branches = [b for b in branches if b != pattern]

    return branches


def has_uncommitted_changes():
    """Check if there are uncommitted changes to tracked files (ignores untracked files)."""
    _, _, working_clean = run_git_command(['diff', '--quiet'], check=False)
    _, _, staged_clean = run_git_command(['diff', '--cached', '--quiet'], check=False)
    return not working_clean or not staged_clean


def is_rebase_in_progress():
    """Check if a rebase or merge is in progress."""
    git_dir_output, _, _ = run_git_command(['rev-parse', '--git-dir'])
    git_dir = Path(git_dir_output)
    return (git_dir / 'rebase-merge').exists() or (git_dir / 'rebase-apply').exists() or \
           (git_dir / 'CHERRY_PICK_HEAD').exists() or (git_dir / 'MERGE_HEAD').exists()


def check_conflicts():
    """Check if there are merge conflicts."""
    _, _, success = run_git_command(['diff', '--check'])
    if not success:
        return True

    output, _, _ = run_git_command(['diff', '--name-only', '--diff-filter=U'])
    return bool(output.strip())


def get_conflicted_files():
    """Return list of conflicted files (U status)."""
    output, _, _ = run_git_command(['diff', '--name-only', '--diff-filter=U'])
    return [f.strip() for f in output.split('\n') if f.strip()]


def get_modified_tex_files():
    """Get list of .tex files that have been modified or are in conflicts."""
    conflict_files = get_conflicted_files()

    staged_output, _, _ = run_git_command(['diff', '--cached', '--name-only'])
    staged_files = [f.strip() for f in staged_output.split('\n') if f.strip()]

    modified_output, _, _ = run_git_command(['diff', '--name-only'])
    modified_files = [f.strip() for f in modified_output.split('\n') if f.strip()]

    all_files = set(conflict_files + staged_files + modified_files)
    return [f for f in all_files if f.endswith('.tex')]


def compile_tex_file(tex_file):
    """Compile a .tex file to .pdf using latexmk (preferred) or pdflatex."""
    tex_path = Path(tex_file)
    if not tex_path.exists():
        print(f"Warning: {tex_file} does not exist. Skipping compilation.")
        return False, None

    pdf_file = tex_path.with_suffix('.pdf')
    cwd = tex_path.parent

    # Try latexmk first
    latexmk_cmd = ['latexmk', '-pdf', '-interaction=nonstopmode', '-halt-on-error', tex_path.name]
    stdout, stderr, success = run_command(latexmk_cmd, cwd=cwd, check=False)

    if not success:
        # Fallback to pdflatex
        print("latexmk failed or not found, trying pdflatex...")
        pdflatex_cmd = ['pdflatex', '-interaction=nonstopmode', '-halt-on-error', tex_path.name]
        stdout, stderr, success = run_command(pdflatex_cmd, cwd=cwd, check=False)
        if success:
            # Run again for references (best-effort)
            run_command(pdflatex_cmd, cwd=cwd, check=False)

    if success and pdf_file.exists():
        return True, str(pdf_file)

    error_msg = stderr if stderr else stdout
    print(f"Compilation failed: {error_msg}")
    return False, None


def open_pdf(pdf_file):
    """Open PDF file using the system's default viewer (cross-platform)."""
    pdf_path = Path(pdf_file)
    if not pdf_path.exists():
        print(f"Error: PDF file {pdf_file} does not exist.")
        return False

    system = platform.system()
    try:
        if system == 'Windows':
            os.startfile(str(pdf_path))
        elif system == 'Darwin':
            subprocess.run(['open', str(pdf_path)])
        else:
            subprocess.run(['xdg-open', str(pdf_path)])
        return True
    except Exception as e:
        print(f"Warning: Could not open PDF automatically: {e}")
        print(f"Please manually open: {pdf_path.absolute()}")
        return False


def handle_tex_files():
    """Compile & verify any modified .tex files, and stage their PDFs."""
    tex_files = get_modified_tex_files()

    if not tex_files:
        return True

    print(f"\n⚠  LaTeX files detected: {len(tex_files)} .tex file(s) modified")
    print("These files need to be recompiled and verified.")

    for tex_file in tex_files:
        print(f"\n{'='*60}")
        print(f"Processing: {tex_file}")
        print(f"{'='*60}")

        print(f"Compiling {tex_file} to PDF...")
        success, pdf_file = compile_tex_file(tex_file)

        if not success:
            response = input(f"Compilation failed for {tex_file}. Continue anyway? (y/n): ").strip().lower()
            if response != 'y':
                return False
            continue

        print(f"✓ Compiled to: {pdf_file}")

        print("\nOpening PDF for review...")
        if not open_pdf(pdf_file):
            print(f"Please manually open: {pdf_file}")

        while True:
            response = input(f"\nHave you reviewed {pdf_file}? Does it look correct? (y/n/retry): ").strip().lower()

            if response == 'y':
                print(f"Staging PDF: {pdf_file}")
                stdout, stderr, ok = run_git_command(['add', pdf_file], check=False)
                if ok:
                    print(f"✓ Staged {pdf_file}")
                    break
                error_msg = stderr if stderr else stdout
                print(f"✗ Failed to stage {pdf_file}: {error_msg}")

            elif response == 'n':
                fix_response = input("PDF is incorrect. Have you fixed the .tex file? (y/n): ").strip().lower()
                if fix_response == 'y':
                    success, pdf_file = compile_tex_file(tex_file)
                    if success:
                        open_pdf(pdf_file)
                        continue
                    print("Compilation failed. You may need to fix issues manually.")
                    continue

                response = input("Continue without fixing? (y/n): ").strip().lower()
                if response == 'y':
                    run_git_command(['add', pdf_file], check=False)
                    break
                return False

            elif response == 'retry':
                success, pdf_file = compile_tex_file(tex_file)
                if success:
                    open_pdf(pdf_file)
                    continue
                print("Compilation failed. Please fix the .tex file manually.")

            else:
                print("Please enter 'y' (yes), 'n' (no), or 'retry'")

    return True


def tex_for_pdf(pdf_path: Path):
    """Best-effort mapping: same directory, same basename, .tex extension."""
    candidate = pdf_path.with_suffix('.tex')
    return candidate if candidate.exists() else None


def handle_conflicted_pdfs():
    """If PDFs are conflicted, try regenerating from matching .tex first (and stage PDFs)."""
    conflicted = get_conflicted_files()
    conflicted_pdfs = [f for f in conflicted if f.lower().endswith('.pdf')]

    if not conflicted_pdfs:
        return True

    print(f"\n⚠  Detected {len(conflicted_pdfs)} conflicted PDF(s).")
    print("Attempting to regenerate them from matching .tex first (this often resolves binary conflicts).")

    conflicted_set = set(conflicted)

    for pdf in conflicted_pdfs:
        pdf_path = Path(pdf)
        print(f"\n{'='*60}")
        print(f"PDF conflict: {pdf}")
        print(f"{'='*60}")

        tex_path = tex_for_pdf(pdf_path)
        if not tex_path:
            print(f"No matching .tex found next to {pdf}. You'll need to resolve this PDF conflict manually.")
            continue

        if str(tex_path).replace('\\', '/').replace('\\\\', '/') in conflicted_set or str(tex_path) in conflicted_set:
            print(f"Matching .tex is also conflicted: {tex_path}")
            print("Resolve the .tex conflict first, then regeneration will work.")
            continue

        while True:
            print(f"Regenerating from: {tex_path}")
            success, built_pdf = compile_tex_file(str(tex_path))
            if not success:
                resp = input("Compilation failed. Fix the .tex and type 'retry', or 'skip' to handle manually, or 'abort': ").strip().lower()
                if resp == 'retry':
                    continue
                if resp == 'abort':
                    return False
                break

            print(f"✓ Regenerated: {built_pdf}")
            print("Opening PDF for review...")
            open_pdf(built_pdf)

            resp = input("Does it look correct? (y=stage & continue, n=edit tex then retry, skip=leave unresolved): ").strip().lower()
            if resp == 'y':
                stdout, stderr, ok = run_git_command(['add', str(pdf_path)], check=False)
                if ok:
                    print(f"✓ Staged {pdf_path} (PDF conflict should be resolved)")
                else:
                    error_msg = stderr if stderr else stdout
                    print(f"✗ Failed to stage {pdf_path}: {error_msg}")
                break
            if resp == 'n':
                # user will edit tex, then we retry compilation
                continue
            if resp == 'skip':
                break
            print("Please enter y, n, or skip")

    return True


def save_state(state_file, commits, current_branch, remaining_branches, failed_branches):
    """Save the current state to a file."""
    commits_data = [
        {'hash': c['hash'], 'subject': c['subject'], 'body': c.get('body', '')}
        for c in commits
    ]

    state = {
        'commits': commits_data,
        'original_branch': current_branch,
        'remaining_branches': remaining_branches,
        'failed_branches': failed_branches,
        'current_branch': None
    }

    try:
        branch_output, _, _ = run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'], check=False)
        if branch_output and branch_output != 'HEAD':
            state['current_branch'] = branch_output
    except Exception:
        pass

    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def load_state(state_file):
    """Load state from a file."""
    if not os.path.exists(state_file):
        return None

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
            # Backward compatibility
            if 'commit_hash' in state and 'commits' not in state:
                state['commits'] = [{'hash': state['commit_hash'], 'subject': '', 'body': ''}]
            return state
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load state file: {e}")
        return None


def cleanup_state(state_file):
    """Delete the state file."""
    if os.path.exists(state_file):
        os.remove(state_file)


def cherry_pick_commits(branch, commits):
    """Cherry-pick one or more commits onto a branch."""
    print(f"\n{'='*60}")
    print(f"Switching to branch: {branch}")
    print(f"{'='*60}")

    stdout, stderr, success = run_git_command(['checkout', branch], check=False)
    if not success:
        error_msg = stderr if stderr else stdout
        print(f"Error: Could not checkout branch '{branch}': {error_msg}")
        return False, 'checkout_failed'

    # Check if all commits are already in this branch
    all_applied = True
    for commit in commits:
        output, _, _ = run_git_command(['branch', '--contains', commit['hash']])
        if branch not in output:
            all_applied = False
            break

    if all_applied:
        commit_refs = ', '.join([c['hash'][:8] for c in commits])
        print(f"All commits ({commit_refs}) are already in branch '{branch}'. Skipping.")
        return True, 'already_applied'

    # Prepare commits for cherry-pick
    if len(commits) == 1:
        print(f"Cherry-picking commit {commits[0]['hash'][:8]} onto branch '{branch}'...")
        print(f"  {commits[0]['subject']}")
        cherry_pick_args = ['cherry-pick', commits[0]['hash']]
    else:
        oldest_hash = commits[0]['hash']
        newest_hash = commits[-1]['hash']
        commit_range = f"{oldest_hash}^..{newest_hash}"
        print(f"Cherry-picking {len(commits)} commits onto branch '{branch}'...")
        for i, commit in enumerate(commits, 1):
            print(f"  {i}. {commit['hash'][:8]}: {commit['subject']}")
        cherry_pick_args = ['cherry-pick', commit_range]

    stdout, stderr, success = run_git_command(cherry_pick_args, check=False)

    if success:
        tex_files = get_modified_tex_files()
        if tex_files:
            print(f"\n⚠  LaTeX files modified during cherry-pick: {len(tex_files)} .tex file(s)")
            if not handle_tex_files():
                print("Warning: LaTeX file handling was aborted, but cherry-pick succeeded.")
                print("You may need to manually compile and commit the PDFs.")

        print(f"✓ Successfully cherry-picked to '{branch}'")
        return True, 'success'

    # Failure path
    if check_conflicts() or is_rebase_in_progress():
        print(f"\n⚠ CONFLICT detected on branch '{branch}'!")
        print("Trying PDF regeneration first (if applicable)...")

        # Show git status for context
        status_out, _, _ = run_git_command(['status'], check=False)
        print("\nGit status:")
        print(status_out)

        # Attempt to auto-resolve PDF conflicts by regenerating from .tex
        if not handle_conflicted_pdfs():
            return False, 'conflict'

        # If that fixed everything, try to continue immediately
        if not check_conflicts():
            if not handle_tex_files():
                print("LaTeX handling was aborted.")
                return False, 'conflict'

            c_out, c_err, c_ok = run_git_command(['cherry-pick', '--continue'], check=False)
            if c_ok:
                print("✓ Cherry-pick continued successfully")
                return True, 'success'
            error_msg = c_err if c_err else c_out
            print(f"Error continuing cherry-pick: {error_msg}")

        return False, 'conflict'

    # Non-conflict failure
    error_msg = stderr if stderr else stdout
    print(f"\n✗ Cherry-pick FAILED on branch '{branch}'")
    print("Error details:")
    print(f"  {error_msg}" if error_msg else "  (No error message provided)")
    status_out, _, _ = run_git_command(['status'], check=False)
    if status_out:
        print("\nGit status:")
        print(status_out)
    return False, 'failed'


def wait_for_resolution():
    """Wait for user to resolve conflicts, but try PDF regeneration first."""
    while True:
        # Always try PDF regeneration first (this can eliminate binary conflicts)
        if not handle_conflicted_pdfs():
            print("Aborting after PDF handling.")
            run_git_command(['cherry-pick', '--abort'], check=False)
            return False

        if check_conflicts():
            print("\nConflicts still detected (likely non-PDF and/or conflicted .tex).")
            print("Resolve remaining conflicts, stage them (git add), then continue.")
            response = input("\nHave you resolved the remaining conflicts? (y/n/status/abort): ").strip().lower()
            if response == 'status':
                status_out, _, _ = run_git_command(['status'], check=False)
                print(status_out)
                continue
            if response == 'abort':
                print("Aborting cherry-pick...")
                run_git_command(['cherry-pick', '--abort'], check=False)
                return False
            if response != 'y':
                continue

            if check_conflicts():
                print("Warning: Conflicts still detected. Please resolve them before continuing.")
                continue

        # No conflicts left; ensure we're still in cherry-pick state
        git_dir_output, _, _ = run_git_command(['rev-parse', '--git-dir'])
        git_dir = Path(git_dir_output)
        if not (git_dir / 'CHERRY_PICK_HEAD').exists():
            print("Warning: Not in cherry-pick state. Was the cherry-pick aborted?")
            response = input("Continue anyway? (y/n): ").strip().lower()
            if response != 'y':
                return False

        # Compile/review .tex outputs now (this is where we always stop to open PDFs)
        if not handle_tex_files():
            print("LaTeX file handling was aborted.")
            response = input("Continue with cherry-pick anyway? (y/n): ").strip().lower()
            if response != 'y':
                return False

        stdout, stderr, success = run_git_command(['cherry-pick', '--continue'], check=False)
        if success:
            print("✓ Cherry-pick continued successfully")
            return True

        error_msg = stderr if stderr else stdout
        print(f"Error continuing cherry-pick: {error_msg}")
        if check_conflicts():
            print("Conflicts still exist. Please resolve them.")
            continue

        print("Unable to continue cherry-pick. You may need to resolve manually.")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Cherry-pick the last commit to all branches',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cherry_pick_all_branches.py
  python cherry_pick_all_branches.py -n 3
  python cherry_pick_all_branches.py --exclude-branch main --exclude-branch develop
  python cherry_pick_all_branches.py --exclude-branch "exp/*" --exclude-branch "*/de/*"
  python cherry_pick_all_branches.py --exclude-branch "feature/*" --exclude-branch "release/*"
  python cherry_pick_all_branches.py -n 5 --state-file .cherry-pick-state.json
        """
    )
    parser.add_argument(
        '--exclude-branch',
        action='append',
        default=[],
        metavar='PATTERN',
        help='Branch or pattern to exclude from cherry-picking (can be used multiple times). '
             'Supports wildcards: exp/*, */de/*, feature/*. Use exact name for specific branch.'
    )
    parser.add_argument(
        '--state-file',
        default='.cherry-pick-state.json',
        help='File to store state for resuming (default: .cherry-pick-state.json)'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from saved state'
    )
    parser.add_argument(
        '-n', '--number',
        type=int,
        default=1,
        metavar='N',
        help='Number of commits to cherry-pick (default: 1)'
    )

    args = parser.parse_args()

    if args.number < 1:
        print("Error: -n must be at least 1.")
        sys.exit(1)

    state = None
    if args.resume or os.path.exists(args.state_file):
        state = load_state(args.state_file)
        if state:
            print("Resuming from saved state...")
            commits = state.get('commits', [])
            if commits:
                if len(commits) == 1:
                    print(f"Commit: {commits[0]['hash'][:8]} - {commits[0].get('subject', '')}")
                else:
                    print(f"Commits to cherry-pick: {len(commits)}")
                    for i, commit in enumerate(commits, 1):
                        print(f"  {i}. {commit['hash'][:8]}: {commit.get('subject', '')}")
            print(f"Original branch: {state.get('original_branch', 'unknown')}")
            print(f"Remaining branches: {len(state['remaining_branches'])}")

            response = input("\nContinue? (y/n): ").strip().lower()
            if response != 'y':
                print("Aborted.")
                sys.exit(0)

    if has_uncommitted_changes() and not is_rebase_in_progress():
        print("Warning: You have uncommitted changes.")
        response = input("Continue anyway? (y/n): ").strip().lower()
        if response != 'y':
            print("Aborted. Please commit or stash your changes first.")
            sys.exit(0)

    if state:
        commits = state.get('commits', [])
        original_branch = state['original_branch']
        branches = state['remaining_branches']
        failed_branches = state.get('failed_branches', [])
    else:
        if args.number == 1:
            commit_hash = get_last_commit_hash()
            commits = [{'hash': commit_hash, 'subject': '', 'body': ''}]
            subject_output, _, _ = run_git_command(['log', '-1', '--format=%s', commit_hash])
            commits[0]['subject'] = subject_output.strip()
        else:
            commits = get_last_n_commits(args.number)
            if len(commits) < args.number:
                print(f"Warning: Only {len(commits)} commit(s) available (requested {args.number}).")

        original_branch = get_current_branch()
        branches = get_all_branches(exclude_current=True, exclude_patterns=args.exclude_branch)
        failed_branches = []

        print(f"\n{'='*60}")
        print("Cherry-pick Tool")
        print(f"{'='*60}")

        if len(commits) == 1:
            print(f"Commit to cherry-pick: {commits[0]['hash'][:8]}")
            print(f"  {commits[0]['subject']}")
        else:
            print(f"Commits to cherry-pick: {len(commits)}")
            for i, commit in enumerate(commits, 1):
                print(f"  {i}. {commit['hash'][:8]}: {commit['subject']}")
                if commit.get('body'):
                    body_first_line = commit['body'].split('\n')[0].strip()
                    if body_first_line:
                        print(f"     {body_first_line}")

        print(f"\nCurrent branch: {original_branch}")
        print(f"Branches to process: {len(branches)}")
        if args.exclude_branch:
            print(f"Exclude patterns: {', '.join(args.exclude_branch)}")

        if branches:
            print("\nSelected branches:")
            display_count = min(15, len(branches))
            for i, branch in enumerate(branches[:display_count], 1):
                print(f"  {i}. {branch}")

            if len(branches) > 15:
                remaining = len(branches) - 15
                print(f"\n⚠  Warning: List truncated. {remaining} more branch(es) will be processed.")

        print(f"{'='*60}\n")

        if not branches:
            print("No branches to process.")
            sys.exit(0)

        response = input("Continue? (y/n): ").strip().lower()
        if response != 'y':
            print("Aborted.")
            sys.exit(0)

    processed = 0
    skipped = 0
    failed = 0

    while branches:
        branch = branches[0]

        save_state(args.state_file, commits, original_branch, branches, failed_branches)

        success, reason = cherry_pick_commits(branch, commits)

        if success:
            processed += 1
            branches.pop(0)
        elif reason == 'conflict':
            if wait_for_resolution():
                processed += 1
                branches.pop(0)
            else:
                print(f"\nSkipping branch '{branch}' after abort.")
                failed_branches.append(branch)
                branches.pop(0)
                failed += 1
        elif reason == 'already_applied':
            skipped += 1
            branches.pop(0)
        else:
            print(f"\nFailed to cherry-pick to '{branch}'. Skipping.")
            failed_branches.append(branch)
            branches.pop(0)
            failed += 1

    cleanup_state(args.state_file)

    if original_branch:
        print(f"\n{'='*60}")
        print(f"Returning to original branch: {original_branch}")
        print(f"{'='*60}")
        run_git_command(['checkout', original_branch], check=False)

    print(f"\n{'='*60}")
    print("Summary:")
    print(f"  Processed: {processed}")
    print(f"  Skipped (already applied): {skipped}")
    print(f"  Failed: {failed}")
    if failed_branches:
        print(f"  Failed branches: {', '.join(failed_branches)}")
    print(f"{'='*60}\n")

    if failed > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
