import argparse
import subprocess
import sys
from urllib.parse import urlparse
from http.server import HTTPServer, SimpleHTTPRequestHandler

parser = argparse.ArgumentParser(prog="Alexandria",
                                 description="Alexandria library is a tool to make backup"
                                 " of a website and manage as your personal flavour",
                                 epilog="Keep and hold")
parser.add_argument("website")

DEBUG = True
EXIT_SUCCESS = 0
BORDER = "*" * 8
LINK_MASK = "\u001b]8;;{}\u001b\\{}\u001b]8;;\u001b\\"

def debug_print(*args):
    if DEBUG:
        print("[DEBUG] ", end="")
        print(*args)

def a_print(*objects):
    print(BORDER + " ", end="")
    print(*objects, end="")
    print(" " + BORDER)

def process_download(website):
    urlp = urlparse(website)
    if not bool(urlp.scheme):
        a_print("Not valid website")
        exit(EXIT_SUCCESS)

    domain = urlp.hostname
    a_print(f"Making a mirror of: {website} at {domain}")

    wget_process = (f"wget --recursive -l 1 --page-requisites --adjust-extension --span-hosts"
                    f" -U 'Mozilla'"
                    f" -e robots=off --random-wait --no-cookies"
                    f" --convert-links --restrict-file-names=windows --domains {domain}"
                    f" --no-parent {website}".split(" "))
    debug_print("command: {}".format(" ".join(wget_process)))

    try:
        subprocess.run(wget_process, check=True)
    except subprocess.CalledProcessError as err:
        a_print(f"Error on {website} :( ")
    else:
        a_print(f"Finished {website}!!!")

def try_open_link(link):
    try:
        subprocess.run(["xdg-open", link], capture_output=True)
    except FileNotFoundError:
        pass

def server(port):
    server_handler = SimpleHTTPRequestHandler

    with HTTPServer(("", port), server_handler) as httpd:
        a_print(f"Start server at {port}")

        link = f"http://localhost:{port}"
        a_print(LINK_MASK.format(link, f"http://localhost:{port}"))
        try_open_link(link)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()
            a_print("bye bye!")
            exit(EXIT_SUCCESS)

def create_index():
    html_contet = """
    <html>
    <head> hi! </head>
    <body>
    hello world!
    </body>
    </html>
    """
    with open("index.html", "w") as index:
        index.writelines(html_contet)

PORT = 8000
if __name__ == "__main__":
    # not args - run server
    if not sys.argv[1:]:
        create_index()
        server(PORT)

    args = parser.parse_args()
    website = args.website

    process_download(website)
