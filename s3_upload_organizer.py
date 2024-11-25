#!/usr/bin/env python

import argparse
import requests
from bs4 import BeautifulSoup
import boto3
from urllib.parse import urljoin
import re
from collections import defaultdict
import sys

def get_s3_path(base_path, file_name):
  # Check if filename starts with 'TB' followed by 4 digits
  tb_match = re.match(r'(TB\d{4}).*', file_name)

  if tb_match:
      # Extract the TB number (e.g., 'TB7217')
      tb_number = tb_match.group(1)
      # Return path with TB subfolder
      return f"{base_path.rstrip('/')}/{tb_number}/{file_name}"
  else:
      # Return base path for non-TB files
      return f"{base_path.rstrip('/')}/{file_name}"

def back_slash_check(s3_path: str) -> str:
  # adds a backslash ("/") if not included when providing the s3 bucket path
  if not s3_path.endswith('/'):
    s3_path = f'{s3_path}/'
  return s3_path

def process_files(base_url, base_s3_path, dry_run=True):
  # Initialize S3 client (not needed for dry run, but kept for consistency)
  s3_client = boto3.client('s3') if not dry_run else None

  # Extract bucket name and prefix from the S3 path
  base_s3_path = back_slash_check(base_s3_path)
  bucket_name = base_s3_path.replace('s3://', '').split('/')[0]
  prefix = '/'.join(base_s3_path.replace('s3://', '').split('/')[1:])

  # Statistics collectors
  stats = {
      'total_files': 0,
      'total_size': 0,
      'folders': defaultdict(list)
  }

  print("\n=== Starting {} ===".format("DRY RUN" if dry_run else "ACTUAL RUN"))
  print(f"Base URL: {base_url}")
  print(f"Target S3: s3://{bucket_name}/{prefix}")
  print("=" * 50 + "\n")

  try:
      # Fetch the webpage
      response = requests.get(base_url)
      soup = BeautifulSoup(response.text, 'html.parser')

      # Find all links within ul/li elements
      file_links = soup.select('ul li a')

      print("Files to be processed:")
      print("-" * 50)

      for link in file_links:
          file_url = urljoin(base_url, link['href'])
          file_name = link.text.strip()
          full_s3_path = get_s3_path(prefix, file_name)

          # Get file size (send HEAD request to avoid downloading)
          file_head = requests.head(file_url)
          file_size = int(file_head.headers.get('content-length', 0))

          # Update statistics
          stats['total_files'] += 1
          stats['total_size'] += file_size

          # Determine folder based on file pattern
          tb_match = re.match(r'(TB\d{4}).*', file_name)
          folder = tb_match.group(1) if tb_match else 'base_folder'
          stats['folders'][folder].append({
              'name': file_name,
              'size': file_size,
              'path': f"s3://{bucket_name}/{full_s3_path}"
          })

          if not dry_run:
              try:
                  print(f"Uploading {file_name}...")
                  # Get the file content as a stream
                  file_response = requests.get(file_url, stream=True)

                  # Upload to S3 using the streaming response
                  s3_client.upload_fileobj(
                      file_response.raw,
                      bucket_name,
                      full_s3_path,
                      ExtraArgs={'ContentType': file_response.headers.get('content-type')}
                  )
                  print(f"Successfully uploaded {file_name}")

              except Exception as e:
                  print(f"Error processing {file_name}: {str(e)}")
                  return 1

      # Print summary
      print("\n=== Summary ===")
      print(f"Total files to process: {stats['total_files']}")
      print(f"Total size: {stats['total_size'] / (1024*1024*1024):.2f} GB")
      print("\nFiles by folder:")

      for folder, files in stats['folders'].items():
          folder_size = sum(f['size'] for f in files)
          print(f"\n{folder}:")
          print(f"  Total files: {len(files)}")
          print(f"  Total size: {folder_size / (1024*1024*1024):.2f} GB")
          print("  Files:")
          for file in files:
              print(f"    - {file['name']} ({file['size'] / (1024*1024):.2f} MB)")
              print(f"      → {file['path']}")

      return 0

  except Exception as e:
      print(f"Error: {str(e)}", file=sys.stderr)
      return 1

def main():
  parser = argparse.ArgumentParser(
      description='Upload files from a webpage to S3, organizing them by TB number patterns.',
      formatter_class=argparse.RawDescriptionHelpFormatter,
      epilog='''
Example usage:
%(prog)s --url https://example.com/files/ --s3-path s3://my-bucket/prefix/ --dry-run
%(prog)s --url https://example.com/files/ --s3-path s3://my-bucket/prefix/ --execute
      '''
  )

  parser.add_argument(
      '--url',
      required=True,
      help='Base URL of the webpage containing the files'
  )

  parser.add_argument(
      '--s3-path',
      required=True,
      help='S3 destination path (e.g., s3://bucket-name/prefix/)'
  )

  parser.add_argument(
      '--dry-run',
      action='store_true',
      default=True,
      help='Show what would be done without actually uploading (default: True)'
  )

  parser.add_argument(
      '--execute',
      action='store_true',
      help='Actually perform the upload (overrides --dry-run)'
  )

  args = parser.parse_args()

  # Validate S3 path format
  if not args.s3_path.startswith('s3://'):
      parser.error("S3 path must start with 's3://'")

  # Execute flag overrides dry-run
  dry_run = not args.execute

  return process_files(args.url, args.s3_path, dry_run)

if __name__ == '__main__':
  sys.exit(main())