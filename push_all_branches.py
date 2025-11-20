#!/usr/bin/env python3
"""
Cross-platform tool to push all branches to remote.
Supports pattern matching for exclusions and shows progress.

Usage:
    python push_all_branches.py [--exclude-branch PATTERN] [--remote REMOTE] [--dry-run]
"""

import subprocess
import sys
import argparse
import fnmatch


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
            # Pattern matching mode
            branches = [b for b in branches if not fnmatch.fnmatch(b, pattern)]
        else:
            # Exact match mode
            branches = [b for b in branches if b != pattern]
    
    return branches


def branch_has_remote(branch, remote):
    """Check if branch has an upstream remote configured."""
    output, _, success = run_git_command(['rev-parse', '--abbrev-ref', f'{branch}@{{upstream}}'], check=False)
    if success:
        # Check if it matches the requested remote
        if remote == 'origin' or output.startswith(f'{remote}/'):
            return True
    return False


def push_branch(branch, remote='origin', dry_run=False, ask_upstream=True):
    """Push a branch to remote."""
    if dry_run:
        has_upstream = branch_has_remote(branch, remote)
        if has_upstream:
            print(f"[DRY RUN] Would push: {branch} -> {remote}/{branch}")
        else:
            print(f"[DRY RUN] Would push: {branch} -> {remote}/{branch} (and set upstream)")
        return True, 'dry_run'
    
    # Check if branch has upstream set
    has_upstream = branch_has_remote(branch, remote)
    
    if has_upstream:
        # Push to existing upstream
        stdout, stderr, success = run_git_command(['push', remote, branch], check=False)
    else:
        # Ask before setting upstream
        if ask_upstream:
            response = input(f"Branch '{branch}' has no upstream. Set upstream to {remote}/{branch}? (y/n/skip): ").strip().lower()
            if response == 'n':
                print(f"Skipping {branch} (upstream not set)")
                return False, 'skipped'
            elif response == 'skip':
                print(f"Skipping {branch} (upstream not set)")
                return False, 'skipped'
            elif response != 'y':
                print(f"Invalid response. Skipping {branch}.")
                return False, 'skipped'
        
        # Push and set upstream
        stdout, stderr, success = run_git_command(['push', '-u', remote, branch], check=False)
    
    if success:
        action = "pushed" if has_upstream else "pushed (upstream set)"
        print(f"✓ {branch} -> {remote}/{branch} ({action})")
        return True, 'success'
    else:
        error_msg = stderr if stderr else stdout
        print(f"✗ Failed to push {branch}: {error_msg}")
        return False, 'failed'


def main():
    parser = argparse.ArgumentParser(
        description='Push all local branches to remote',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python push_all_branches.py
  python push_all_branches.py --exclude-branch main --exclude-branch develop
  python push_all_branches.py --exclude-branch "exp/*" --exclude-branch "*/de/*"
  python push_all_branches.py --remote upstream
  python push_all_branches.py --dry-run
  python push_all_branches.py --exclude-current
  python push_all_branches.py --auto-set-upstream
        """
    )
    parser.add_argument(
        '--exclude-branch',
        action='append',
        default=[],
        metavar='PATTERN',
        help='Branch or pattern to exclude from pushing (can be used multiple times). '
             'Supports wildcards: exp/*, */de/*, feature/*'
    )
    parser.add_argument(
        '--remote',
        default='origin',
        help='Remote name to push to (default: origin)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be pushed without actually pushing'
    )
    parser.add_argument(
        '--exclude-current',
        action='store_true',
        help='Exclude the current branch from pushing'
    )
    parser.add_argument(
        '--no-confirm',
        action='store_true',
        help='Skip confirmation prompt'
    )
    parser.add_argument(
        '--auto-set-upstream',
        action='store_true',
        help='Automatically set upstream for branches without one (skip confirmation prompt)'
    )
    
    args = parser.parse_args()
    
    # Check if remote exists
    remotes_output, _, success = run_git_command(['remote'])
    if not success or args.remote not in remotes_output.split('\n'):
        print(f"Error: Remote '{args.remote}' not found.")
        print(f"Available remotes: {', '.join(remotes_output.split()) if remotes_output else 'none'}")
        sys.exit(1)
    
    # Get branches to push
    branches = get_all_branches(exclude_current=args.exclude_current, exclude_patterns=args.exclude_branch)
    current_branch = get_current_branch()
    
    if not branches:
        print("No branches to push.")
        sys.exit(0)
    
    print(f"\n{'='*60}")
    print(f"Push All Branches")
    print(f"{'='*60}")
    print(f"Remote: {args.remote}")
    print(f"Current branch: {current_branch}")
    print(f"Branches to push: {len(branches)}")
    if args.exclude_branch:
        print(f"Exclude patterns: {', '.join(args.exclude_branch)}")
    if args.dry_run:
        print(f"Mode: DRY RUN (no changes will be made)")
    print(f"{'='*60}")
    
    # Display branches (up to 15)
    if branches:
        print(f"\nBranches to push:")
        display_count = min(15, len(branches))
        for i, branch in enumerate(branches[:display_count], 1):
            print(f"  {i}. {branch}")
        
        if len(branches) > 15:
            remaining = len(branches) - 15
            print(f"\n⚠  Warning: List truncated. {remaining} more branch(es) will be pushed.")
    
    print(f"{'='*60}\n")
    
    # Confirm before proceeding
    if not args.no_confirm:
        response = input("Continue? (y/n): ").strip().lower()
        if response != 'y':
            print("Aborted.")
            sys.exit(0)
    
    # Push each branch
    successful = 0
    failed = 0
    skipped = 0
    skipped_branches = []
    failed_branches = []
    
    # Determine if we should ask about upstream
    ask_upstream = not args.auto_set_upstream
    
    for branch in branches:
        success, reason = push_branch(branch, args.remote, args.dry_run, ask_upstream=ask_upstream)
        if success:
            if reason == 'dry_run':
                skipped += 1
            else:
                successful += 1
        elif reason == 'skipped':
            skipped += 1
            skipped_branches.append(branch)
        else:
            failed += 1
            failed_branches.append(branch)
    
    # Summary
    print(f"\n{'='*60}")
    print("Summary:")
    if args.dry_run:
        print(f"  Would push: {skipped}")
    else:
        print(f"  Successfully pushed: {successful}")
        if skipped > 0:
            print(f"  Skipped: {skipped}")
            if skipped_branches:
                print(f"  Skipped branches: {', '.join(skipped_branches)}")
        if failed > 0:
            print(f"  Failed: {failed}")
            if failed_branches:
                print(f"  Failed branches: {', '.join(failed_branches)}")
    print(f"{'='*60}\n")
    
    if failed > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()

