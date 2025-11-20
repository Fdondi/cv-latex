#!/usr/bin/env python3
"""
Cross-platform tool to cherry-pick the last commit to all branches.
Pauses on conflicts and resumes after resolution.

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
        # Get commit subject (first line of commit message)
        subject_output, _, _ = run_git_command(['log', '-1', '--format=%s', commit_hash])
        subject = subject_output.strip()
        
        # Get commit body (rest of commit message, if any)
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
        # This supports both exact branch names and patterns like exp/*, */de/*, etc.
        if '*' in pattern or '?' in pattern or '[' in pattern:
            # Pattern matching mode
            branches = [b for b in branches if not fnmatch.fnmatch(b, pattern)]
        else:
            # Exact match mode (backward compatible)
            branches = [b for b in branches if b != pattern]
    
    return branches


def has_uncommitted_changes():
    """Check if there are uncommitted changes to tracked files (ignores untracked files)."""
    # Use git diff to check for changes to tracked files only
    # --quiet returns exit code 0 if no changes, non-zero if there are changes
    # Check both working directory (unstaged) and staged changes
    _, _, working_clean = run_git_command(['diff', '--quiet'], check=False)
    _, _, staged_clean = run_git_command(['diff', '--cached', '--quiet'], check=False)
    
    # working_clean/staged_clean is True if no changes, False if there are changes
    # Return True if there are any changes (either unstaged or staged)
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


def get_modified_tex_files():
    """Get list of .tex files that have been modified or are in conflicts."""
    # Get files with conflicts
    conflict_output, _, _ = run_git_command(['diff', '--name-only', '--diff-filter=U'])
    conflict_files = [f.strip() for f in conflict_output.split('\n') if f.strip()]
    
    # Get staged files (after resolution)
    staged_output, _, _ = run_git_command(['diff', '--cached', '--name-only'])
    staged_files = [f.strip() for f in staged_output.split('\n') if f.strip()]
    
    # Get modified files in working directory
    modified_output, _, _ = run_git_command(['diff', '--name-only'])
    modified_files = [f.strip() for f in modified_output.split('\n') if f.strip()]
    
    # Combine all and filter for .tex files
    all_files = set(conflict_files + staged_files + modified_files)
    tex_files = [f for f in all_files if f.endswith('.tex')]
    
    return tex_files


def compile_tex_file(tex_file):
    """Compile a .tex file to .pdf using pdflatex or latexmk."""
    tex_path = Path(tex_file)
    if not tex_path.exists():
        print(f"Warning: {tex_file} does not exist. Skipping compilation.")
        return False, None
    
    # Try latexmk first (more robust), fallback to pdflatex
    pdf_file = tex_path.with_suffix('.pdf')
    
    # Try latexmk (common on Windows with MiKTeX, Linux with TeX Live)
    stdout, stderr, success = run_git_command(['latexmk', '-pdf', '-interaction=nonstopmode', str(tex_path)], check=False)
    
    if not success:
        # Fallback to pdflatex
        print(f"latexmk not found, trying pdflatex...")
        stdout, stderr, success = run_git_command(['pdflatex', '-interaction=nonstopmode', str(tex_path)], check=False)
        
        if success:
            # Run pdflatex again for references (if needed)
            run_git_command(['pdflatex', '-interaction=nonstopmode', str(tex_path)], check=False)
    
    if success and pdf_file.exists():
        return True, str(pdf_file)
    else:
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
        elif system == 'Darwin':  # macOS
            subprocess.run(['open', str(pdf_path)])
        else:  # Linux and others
            subprocess.run(['xdg-open', str(pdf_path)])
        return True
    except Exception as e:
        print(f"Warning: Could not open PDF automatically: {e}")
        print(f"Please manually open: {pdf_path.absolute()}")
        return False


def handle_tex_files():
    """Handle .tex files after conflict resolution: compile and verify."""
    tex_files = get_modified_tex_files()
    
    if not tex_files:
        return True  # No .tex files to handle
    
    print(f"\n⚠  LaTeX files detected: {len(tex_files)} .tex file(s) modified")
    print("These files need to be recompiled and verified.")
    
    for tex_file in tex_files:
        print(f"\n{'='*60}")
        print(f"Processing: {tex_file}")
        print(f"{'='*60}")
        
        # Compile .tex to .pdf
        print(f"Compiling {tex_file} to PDF...")
        success, pdf_file = compile_tex_file(tex_file)
        
        if not success:
            response = input(f"Compilation failed for {tex_file}. Continue anyway? (y/n): ").strip().lower()
            if response != 'y':
                return False
            continue
        
        print(f"✓ Compiled to: {pdf_file}")
        
        # Open PDF for user to check
        print(f"\nOpening PDF for review...")
        if not open_pdf(pdf_file):
            print(f"Please manually open: {pdf_file}")
        
        # Ask user to verify
        while True:
            response = input(f"\nHave you reviewed {pdf_file}? Does it look correct? (y/n/retry): ").strip().lower()
            
            if response == 'y':
                # User confirmed, stage the new PDF
                print(f"Staging new PDF: {pdf_file}")
                stdout, stderr, success = run_git_command(['add', pdf_file], check=False)
                if success:
                    print(f"✓ Staged {pdf_file}")
                    break
                else:
                    error_msg = stderr if stderr else stdout
                    print(f"✗ Failed to stage {pdf_file}: {error_msg}")
                    response = input("Continue anyway? (y/n): ").strip().lower()
                    if response == 'y':
                        break
                    continue
            
            elif response == 'n':
                # User says PDF is wrong
                fix_response = input("PDF is incorrect. Have you fixed the .tex file? (y/n): ").strip().lower()
                if fix_response == 'y':
                    # Recompile after user fixes
                    success, pdf_file = compile_tex_file(tex_file)
                    if success:
                        open_pdf(pdf_file)
                        continue  # Ask again
                    else:
                        print("Compilation failed. You may need to fix issues manually.")
                        continue
                else:
                    response = input("Continue without fixing? (y/n): ").strip().lower()
                    if response == 'y':
                        # Stage PDF anyway
                        run_git_command(['add', pdf_file], check=False)
                        break
                    else:
                        return False  # User wants to abort
            
            elif response == 'retry':
                # Recompile
                success, pdf_file = compile_tex_file(tex_file)
                if success:
                    open_pdf(pdf_file)
                    continue
                else:
                    print("Compilation failed. Please fix the .tex file manually.")
                    continue
            
            else:
                print("Please enter 'y' (yes), 'n' (no), or 'retry'")
    
    return True  # All .tex files handled


def save_state(state_file, commits, current_branch, remaining_branches, failed_branches):
    """Save the current state to a file."""
    # Convert commits to serializable format
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
    
    # Try to get current branch (might be in detached HEAD state)
    try:
        branch_output, _, _ = run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'], check=False)
        if branch_output and branch_output != 'HEAD':
            state['current_branch'] = branch_output
    except:
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
            # Handle backward compatibility: if state has 'commit_hash', convert to 'commits'
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
    # Switch to the branch
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
        # For multiple commits, use range format: oldest^..newest
        # This includes oldest through newest (all commits)
        oldest_hash = commits[0]['hash']
        newest_hash = commits[-1]['hash']
        # Format: A^..B means "from parent of A to B" which includes A through B
        commit_range = f"{oldest_hash}^..{newest_hash}"
        print(f"Cherry-picking {len(commits)} commits onto branch '{branch}'...")
        for i, commit in enumerate(commits, 1):
            print(f"  {i}. {commit['hash'][:8]}: {commit['subject']}")
        cherry_pick_args = ['cherry-pick', commit_range]
    
    # Attempt cherry-pick
    stdout, stderr, success = run_git_command(cherry_pick_args, check=False)
    
    if success:
        # Check for modified .tex files even if no conflicts occurred
        # This handles cases where .tex files were modified during cherry-pick
        tex_files = get_modified_tex_files()
        if tex_files:
            print(f"\n⚠  LaTeX files modified during cherry-pick: {len(tex_files)} .tex file(s)")
            if not handle_tex_files():
                print("Warning: LaTeX file handling was aborted, but cherry-pick succeeded.")
                print("You may need to manually compile and commit the PDFs.")
        
        print(f"✓ Successfully cherry-picked to '{branch}'")
        return True, 'success'
    else:
        # Check if it's a conflict
        if check_conflicts() or is_rebase_in_progress():
            print(f"\n⚠ CONFLICT detected on branch '{branch}'!")
            print(f"Please resolve the conflicts manually.")
            print(f"\nGit status:")
            status_out, _, _ = run_git_command(['status'], check=False)
            print(status_out)
            return False, 'conflict'
        else:
            # Show detailed error message
            error_msg = stderr if stderr else stdout
            print(f"\n✗ Cherry-pick FAILED on branch '{branch}'")
            print(f"Error details:")
            if error_msg:
                print(f"  {error_msg}")
            else:
                print(f"  (No error message provided)")
            # Also show git status for more context
            status_out, _, _ = run_git_command(['status'], check=False)
            if status_out:
                print(f"\nGit status:")
                print(status_out)
            return False, 'failed'


def wait_for_resolution():
    """Wait for user to resolve conflicts and handle .tex files if needed."""
    while True:
        response = input("\nHave you resolved the conflicts? (y/n/abort): ").strip().lower()
        
        if response == 'y':
            # Check if conflicts are actually resolved
            if check_conflicts():
                print("Warning: Conflicts still detected. Please resolve them before continuing.")
                continue
            
            # Check if we're still in cherry-pick state
            git_dir_output, _, _ = run_git_command(['rev-parse', '--git-dir'])
            git_dir = Path(git_dir_output)
            if not (git_dir / 'CHERRY_PICK_HEAD').exists():
                print("Warning: Not in cherry-pick state. Was the cherry-pick aborted?")
                response = input("Continue anyway? (y/n): ").strip().lower()
                if response != 'y':
                    return False
            
            # Handle .tex files: compile and verify PDFs
            # This must happen before continuing cherry-pick
            if not handle_tex_files():
                print("LaTeX file handling was aborted.")
                response = input("Continue with cherry-pick anyway? (y/n): ").strip().lower()
                if response != 'y':
                    return False
            
            # Try to continue the cherry-pick
            stdout, stderr, success = run_git_command(['cherry-pick', '--continue'], check=False)
            if success:
                print("✓ Cherry-pick continued successfully")
                return True
            else:
                error_msg = stderr if stderr else stdout
                print(f"Error continuing cherry-pick: {error_msg}")
                if check_conflicts():
                    print("Conflicts still exist. Please resolve them.")
                    continue
                else:
                    print("Unable to continue cherry-pick. You may need to resolve manually.")
                    return False
        
        elif response == 'n':
            continue
        
        elif response == 'abort':
            print("Aborting cherry-pick...")
            run_git_command(['cherry-pick', '--abort'], check=False)
            return False
        
        else:
            print("Please enter 'y' (yes), 'n' (no), or 'abort'")


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
    
    # Validate -n parameter
    if args.number < 1:
        print("Error: -n must be at least 1.")
        sys.exit(1)
    
    # Load state if resuming
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
    
    # Check for uncommitted changes
    if has_uncommitted_changes() and not is_rebase_in_progress():
        print("Warning: You have uncommitted changes.")
        response = input("Continue anyway? (y/n): ").strip().lower()
        if response != 'y':
            print("Aborted. Please commit or stash your changes first.")
            sys.exit(0)
    
    # Initialize or restore state
    if state:
        commits = state.get('commits', [])
        original_branch = state['original_branch']
        branches = state['remaining_branches']
        failed_branches = state.get('failed_branches', [])
    else:
        # Get commits to cherry-pick
        if args.number == 1:
            commit_hash = get_last_commit_hash()
            commits = [{'hash': commit_hash, 'subject': '', 'body': ''}]
            # Get commit subject for display
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
        print(f"Cherry-pick Tool")
        print(f"{'='*60}")
        
        # Display commit(s) information
        if len(commits) == 1:
            print(f"Commit to cherry-pick: {commits[0]['hash'][:8]}")
            print(f"  {commits[0]['subject']}")
        else:
            print(f"Commits to cherry-pick: {len(commits)}")
            for i, commit in enumerate(commits, 1):
                print(f"  {i}. {commit['hash'][:8]}: {commit['subject']}")
                if commit.get('body'):
                    # Show first line of body if it exists
                    body_first_line = commit['body'].split('\n')[0].strip()
                    if body_first_line:
                        print(f"     {body_first_line}")
        
        print(f"\nCurrent branch: {original_branch}")
        print(f"Branches to process: {len(branches)}")
        if args.exclude_branch:
            print(f"Exclude patterns: {', '.join(args.exclude_branch)}")
        
        # Display branches (up to 15)
        if branches:
            print(f"\nSelected branches:")
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
    
    # Process each branch
    processed = 0
    skipped = 0
    failed = 0
    
    while branches:
        branch = branches[0]
        
        # Save state before processing
        save_state(args.state_file, commits, original_branch, branches, failed_branches)
        
        success, reason = cherry_pick_commits(branch, commits)
        
        if success:
            processed += 1
            branches.pop(0)
        elif reason == 'conflict':
            # Wait for user to resolve
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
    
    # Cleanup and return to original branch
    cleanup_state(args.state_file)
    
    if original_branch:
        print(f"\n{'='*60}")
        print(f"Returning to original branch: {original_branch}")
        print(f"{'='*60}")
        run_git_command(['checkout', original_branch], check=False)
    
    # Summary
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

