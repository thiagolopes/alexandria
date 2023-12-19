import argparse
import subprocess
from urllib.parse import urlparse

parser = argparse.ArgumentParser(prog="Alexandria",
                                 description="Alexandria library is a tool to make backup"
                                 " of a website and manage as your personal flavour",
                                 epilog="Keep and hold")
parser.add_argument("website")

BORDER = "*" * 8
def a_print(*objects):
    print(BORDER + " ", end="")
    print(*objects, end="")
    print(" " + BORDER)
    print("")

def process_download(website):
    urlp = urlparse(website)
    if not bool(urlp.scheme):
        a_print("Not valid website")
        exit(1)

    domain = urlp.hostname
    a_print(f"Making a mirror of: {website} at {domain}")

    wget_process = (f"wget --recursive --page-requisites --adjust-extension --span-hosts"
                    f" --convert-links --restrict-file-names=windows --domains {domain}"
                    f" --no-parent {website}".split(" "))
    subprocess.run(wget_process)

    a_print(f"Finished {website}!!!")

if __name__ == "__main__":
    args = parser.parse_args()

    website = args.website
    process_download(website)
