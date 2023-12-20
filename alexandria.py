import html
import re
from datetime import datetime
from pathlib import Path
import pickle
import argparse
import subprocess
import sys
import os
from urllib.parse import urlparse
from http.server import HTTPServer, SimpleHTTPRequestHandler

parser = argparse.ArgumentParser(prog="Alexandria",
                                 description="Alexandria library is a tool to make backup"
                                 " of a website and manage as a index",
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

if DEBUG:
    def todo():
        a_print("TODO!!!")

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

def create_index(table):
    css = """

*,
*:before,
*:after {
  box-sizing: border-box;
  font-size: 1rem;
  margin: 0;
  padding: 0;
}

html {
  font-size: 16px;
  font-family: serif;
  color: #252525;
}

body {
  background: #a8c0ff;  /* fallback for old browsers */
  border: 2vh solid rgba(159, 228, 196, 0.5);
  min-height: 100vh;
  padding: 2.5vw;
}

h1 {
  text-align: right;
  font-size: 5vw;
  font-style: italic;
  letter-spacing: 0.25vw;
  color: rgb(35, 63, 51);
}

h2 {
  text-align: right;
  font-size: 1.5vw;
  font-style: italic;
  letter-spacing: 0.25vw;
  color: #485a88;
}

hr {
  margin: 2vh 0;
  height: 2px;
  border: transparent;
  background: rgb(139, 228, 189, 0.5);
}

table {
  border-width: 2px;
  border-color: rgba(159, 228, 196, 0.5);
  border-style: dashed;
  width: 100%;
  border-collapse: collapse;
  font-family: sans-serif;
  font-weight: 400;
}

th {
  padding: 0.5rem;
  background: rgb(53, 85, 71);
  color: rgb(139, 228, 189);
  font-weight: 400;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  font-size: 0.85rem;
}

tr {
  border: 1px solid rgba(255,255,255,0.3);
}

td {
  padding: 0.5rem;
  text-align: center;
  color: rgb(35, 63, 51);
  background: rgb(139, 228, 189);
}

a,
a:visited,
a:focus,
a:active {
  padding: 0.5rem;
  color: #485a88;
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}
    """
    html_contet =f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="ie=edge">
    <title>Alexandria - Home</title>
    <style>
    {css}
    </style>
  </head>
  <body>
    <main>
        <h1>Welcome to Alexandria</h1>
        <h2>Your private library</h2>

        <hr />

        <table>
          <tr>
            <th>URL</th>
            <th>Title</th>
            <th>Size</th>
            <th>Created at</th>
          </tr>
          {table}
        </table>

    </main>
	<script src="index.js"></script>
  </body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as index:
        index.writelines(html_contet)


class WebsiteMirror:
    title_re = re.compile(r"<title.*?>(.+?)</title>")

    def __init__(self, url, dt=None):
        self.url = url
        self.path = self.path_from_url(url)
        self.title = self.grep_title_from_file(self.path)
        self.size = self.calculate_size_disk(self.path.split("/")[0])

        if dt is None:
            debug_print(f"Generated - {self.url}")
            self.created_at = datetime.now()
        else:
            debug_print(f"Reloaded - {self.url}")
            self.created_at = dt


    def __hash__(self):
        return hash(self.url)

    def __eq__(self, other):
        return other.url == self.url

    def __repr__(self):
        return f"<Mirror url={self.url}>"

    def __str__(self):
        return self.url

    def path_from_url(self, url):
        p = urlparse(url)
        return p.netloc + p.path

    def grep_title_from_file(self, path):
        file_text = ""
        # BUG index.html is not constant...
        with open(path + "/index.html", "r") as f:
            for l in f.readlines():
                file_text += l
                f = self.title_re.search(file_text)
                if f:
                    return html.unescape(f.groups()[0])

        assert False
        return "unreach!"

    def calculate_size_disk(self, path):
        total = 0
        with os.scandir(path) as f:
            for e in f:
                if e.is_dir():
                    total += self.calculate_size_disk(e.path)
                if e.is_file():
                    total += e.stat().st_size
        return total

    def to_html(self):
        human_date = self.created_at.strftime("%A, %d. %B %Y %I:%M%p")
        human_size = (self.size // 1024) / 1024 # TODO move me
        return f"""<tr>
            <td><a href="{self.path}">{self.url}</a></td>
            <td>{self.title}</td>
            <td>{human_size} MiB</td>
            <td>{human_date}</td>
            </tr>"""

    @classmethod
    def from_mirror(cls, other):
        # Regenerate mirror from other mirror
        return cls(other.url, other.created_at)

class MirrorsFile():
    default = list

    def __init__(self, path):
        self.path = path
        self.init_if_need(path)

        with open(path, "rb") as f:
            mirrors_file = pickle.load(f)

        self.data = self.default()
        for mirror in mirrors_file:
            self.add(WebsiteMirror.from_mirror(mirror))

        debug_print("MirrorsFile loaded!")
        debug_print(f"Mirrors: {self.data}")

    @classmethod
    def init_if_need(cls, path):
        file_disk = Path(path)
        if not file_disk.exists():
            with open(path, "wb") as f:
                pickle.dump(cls.default(), f, pickle.HIGHEST_PROTOCOL)

    def to_html(self):
        todo() # TODO generate all table here;
        return " ".join(m.to_html() for m in self.data)

    def add(self, mirror):
        self.data.append(mirror)
        self.data = list(dict.fromkeys(self.data))

    def save(self):
        # keeps its overwriting, redo keeping writing and append if it get wrost
        with open(self.path, "wb") as f:
            pickle.dump(self.data, f, pickle.HIGHEST_PROTOCOL)

PORT = 8000
if __name__ == "__main__":
    mirrors = MirrorsFile("data")

    # not args - run server
    if not sys.argv[1:]:
        create_index(mirrors.to_html()) # TODO generate index for each request, need overwrite simplehttphandler
        server(PORT)

    args = parser.parse_args()
    website = args.website

    process_download(website)
    mirror = WebsiteMirror(website)
    mirrors.add(mirror)
    mirrors.save()
