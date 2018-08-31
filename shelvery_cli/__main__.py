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
        # for create data buckets, engine does not matter,
        # probably should extract all S3 things in separate class
    if len(args) == 1 and args[0] == 'create_data_buckets':
        args.insert(0, 'ebs')
    if len(args) < 2:
        print("""Usage: shelvery <backup_type> <action>\n\nBackup types: rds ebs rds_cluster ec2ami redshift
Actions:\n\tcreate_backups\n\tclean_backups\n\tcreate_data_buckets\n\tpull_shared_backups""")
        exit(-2)

    setup_logging()
    main_runner = ShelveryCliMain()
    main_runner.main(args[0], args[1])


if __name__ == "__main__":
    main()
