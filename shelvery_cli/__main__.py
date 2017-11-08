import shelvery
from shelvery_cli.shelver_cli_main import ShelveryCliMain
import logging
import sys


def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    root.addHandler(ch)


def main(args=None):
    """The main routine."""
    
    print(f"Shelvery v{shelvery.__version__}")
    
    if args is None:
        args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: shelvery <backup_type> <action>\n\nBackup types: rds ebs\nActions: create_backups clean_backups")
        exit(-2)
    
    setup_logging()
    main_runner = ShelveryCliMain()
    main_runner.main(args[0], args[1])


if __name__ == "__main__":
    main()
