import subprocess
import os

def backup_files():
    # Source directory root
    source_root = "D:\\"
    # Destination directory root
    backup_root = "C:\\backup"
    
    # List of specific folders to backup
    folders = [
        "Notes",
        "Scripts",
        "swilliams543"
    ]

    # Robocopy options
    # /MIR : Mirror a directory tree (equivalent to /E plus /PURGE).
    # /R:3 : Retry 3 times on failed copies.
    # /W:2 : Wait 2 seconds between retries.
    # /MT  : Multi-threaded copying for performance.
    robocopy_opts = ["/MIR", "/R:3", "/W:2", "/MT"]

    print(f"Starting backup from {source_root} to {backup_root}...")

    # Ensure backup root exists
    if not os.path.exists(backup_root):
        try:
            os.makedirs(backup_root)
        except OSError as e:
            print(f"Error creating backup root directory: {e}")
            return

    for folder in folders:
        src = os.path.join(source_root, folder)
        dst = os.path.join(backup_root, folder)
        
        print(f"Processing: {folder}")
        
        # Construct command: robocopy source dest [options]
        cmd = ["robocopy", src, dst] + robocopy_opts
        
        try:
            # Run robocopy
            # Robocopy exit codes 0-7 indicate success/partial success
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode < 8:
                print(f"  [SUCCESS] Backup of '{folder}' complete. (Code: {result.returncode})")
            else:
                print(f"  [ERROR] Backup of '{folder}' failed. (Code: {result.returncode})")
                print(result.stdout)
        except Exception as e:
            print(f"  [EXCEPTION] Could not run backup for '{folder}': {e}")

    print("Backup job finished.")

if __name__ == "__main__":
    backup_files()