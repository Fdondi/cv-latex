#!/usr/bin/env python3
"""
Script to copy PDFs from different branches to target filenames.

This script:
1. Checks out each specified branch
2. Copies cv.pdf to the target filename
3. Returns to the original branch

Usage:
    python recreate_pdfs.py [--source-pdf FILE] [--dry-run]
"""

import subprocess
import sys
import os
import argparse
import platform
import shutil
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


def checkout_branch(branch):
    """Checkout a branch."""
    stdout, stderr, success = run_git_command(['checkout', branch], check=False)
    if not success:
        error_msg = stderr if stderr else stdout
        print(f"Error: Could not checkout branch '{branch}': {error_msg}")
        return False
    return True




def copy_pdf(source_pdf, target_pdf):
    """Copy PDF file to target location."""
    source_path = Path(source_pdf)
    target_path = Path(target_pdf)
    
    if not source_path.exists():
        print(f"Error: Source PDF {source_pdf} does not exist.")
        return False
    
    try:
        # Ensure target directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy the file
        shutil.copy2(source_path, target_path)
        print(f"✓ Copied {source_pdf} → {target_pdf}")
        return True
    except Exception as e:
        print(f"Error copying PDF: {e}")
        return False


def main():

    branch_mappings = [
        ('main', 'cv_en.pdf'),
        ('versions/en/programming', 'cv_en_p.pdf'),
        ('versions/en/data', 'cv_en_d.pdf'),
        ('versions/de/main', 'cv_de.pdf'),
    ]
    parser = argparse.ArgumentParser(
        description='Recreate PDFs from different branches',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Branch to PDF mappings:{'\n'.join([f'  {branch} → {pdf}' for branch, pdf in branch_mappings])}

Examples:
  python recreate_pdfs.py
  python recreate_pdfs.py --source-pdf cv.pdf
  python recreate_pdfs.py --dry-run
        """
    )
    parser.add_argument(
        '--source-pdf',
        default='cv.pdf',
        help='Name of the source PDF file to copy (default: cv.pdf)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually doing it'
    )
    
    args = parser.parse_args()
    
    # Get current branch
    original_branch = get_current_branch()
    if not original_branch:
        print("Error: Could not determine current branch.")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print(f"Copy PDFs from Branches")
    print(f"{'='*60}")
    print(f"Current branch: {original_branch}")
    print(f"Source PDF: {args.source_pdf}")
    print(f"Branches to process:\n{'\n'.join([f'  {branch} → {pdf}' for branch, pdf in branch_mappings])}")
    if args.dry_run:
        print(f"Mode: DRY RUN")
    print(f"{'='*60}\n")
    
    if not args.dry_run:
        response = input("Continue? (y/n): ").strip().lower()
        if response != 'y':
            print("Aborted.")
            sys.exit(0)
    
    results = []
    
    for branch, target_pdf in branch_mappings:
        print(f"\n{'='*60}")
        print(f"Processing: {branch} → {target_pdf}")
        print(f"{'='*60}")
        
        if args.dry_run:
            print(f"[DRY RUN] Would checkout {branch}")
            print(f"[DRY RUN] Would copy {args.source_pdf} → {target_pdf}")
            results.append((branch, target_pdf, 'dry_run'))
            continue
        
        # Checkout branch
        print(f"Checking out branch: {branch}")
        if not checkout_branch(branch):
            print(f"✗ Failed to checkout {branch}")
            results.append((branch, target_pdf, 'checkout_failed'))
            continue
        
        # Check if source PDF exists
        source_pdf_path = Path(args.source_pdf)
        if not source_pdf_path.exists():
            print(f"✗ Source PDF not found: {args.source_pdf}")
            results.append((branch, target_pdf, 'pdf_not_found'))
            continue
        
        print(f"✓ Found source PDF: {args.source_pdf}")
        
        # Copy PDF to target location
        if not copy_pdf(args.source_pdf, target_pdf):
            print(f"✗ Failed to copy PDF for {branch}")
            results.append((branch, target_pdf, 'copy_failed'))
            continue
        
        results.append((branch, target_pdf, 'success'))
    
    # Return to original branch
    if not args.dry_run and original_branch:
        print(f"\n{'='*60}")
        print(f"Returning to original branch: {original_branch}")
        print(f"{'='*60}")
        checkout_branch(original_branch)
    
    # Summary
    print(f"\n{'='*60}")
    print("Summary:")
    for branch, target_pdf, status in results:
        if status == 'success':
            print(f"  ✓ {branch} → {target_pdf}")
        elif status == 'dry_run':
            print(f"  [DRY RUN] {branch} → {target_pdf}")
        else:
            print(f"  ✗ {branch} → {target_pdf} ({status})")
    print(f"{'='*60}\n")
    
    # Exit with error if any failed
    if any(status not in ('success', 'dry_run') for _, _, status in results):
        sys.exit(1)


if __name__ == '__main__':
    main()

