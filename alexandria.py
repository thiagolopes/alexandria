import argparse
import html
import os
import pickle
import re
import subprocess
import sys
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ALEXANDRIA_PATH = "alx/"
DATABASE = ALEXANDRIA_PATH + "database"
DATABASE_README = ALEXANDRIA_PATH + "README.md"
MIRRORS_PATH = ALEXANDRIA_PATH + "mirrors/"
DATETIME_FMT = "%A, %d. %B %Y %I:%M%p"
DEFAULT_PORT = 8000
DEBUG = False
EXIT_SUCCESS = 0
BORDER_PRINT = "*" * 8
LINK_MASK = "\u001b]8;;{}\u001b\\{}\u001b]8;;\u001b\\"
KB = 1024
MAX_TRUNC = 45

parser = argparse.ArgumentParser(prog="Alexandria",
                                 description="A tool to manage your personal website backup libary",
                                 epilog="Keep and hold")
parser.add_argument("website", help="An internet link (URL)", nargs="?",)
parser.add_argument("-p", "--port", help="The port to run server, 8000 is default", default=DEFAULT_PORT, type=int)
parser.add_argument("-v", "--verbose", help="Enable verbose", default=DEBUG, action=argparse.BooleanOptionalAction, type=bool)
parser.add_argument("-s", "--skip", help="Skip download process, only add entry.", default=False, action=argparse.BooleanOptionalAction, type=bool)

def debug_print(*args, **kwargs):
    border = kwargs.pop("border", False)
    times_border = 6
    if DEBUG:
        if border:
            print(BORDER_PRINT * times_border)
        print("[DEBUG] ", end="")
        print(*args)
        if border:
            print(BORDER_PRINT * times_border)

def title_print(*args):
    print("\n" + BORDER_PRINT + " ", end="")
    print(*args, end="")
    print(" " + BORDER_PRINT)

class HTTPServerAlexandria(SimpleHTTPRequestHandler):
    server_version = "HTTPServerAlexandria"

    svg_icon = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>
<circle cx='50' cy='50' r='50'/>
</svg>"""

    svg_logo = """<svg height='80px' width='80px' version='1.1'
id='Capa_1' xmlns='http://www.w3.org/2000/svg'
xmlns:xlink='http://www.w3.org/1999/xlink' viewBox='0 0 425.45 425.45' xml:space='preserve'>
<path d='M267.087,74.755c6.359,3.934,13.87,6.261,21.68,6.261c22.346,0,40.525-18.18,40.525-40.525
c0-21.746-17.219-39.54-38.737-40.48c-0.147-0.015-155.511-0.015-155.658,0C113.378,0.95,96.159,18.744,96.159,40.49
c0,22.346,18.18,40.525,40.525,40.525c7.808,0,15.316-2.326,21.674-6.257c1.983,1.021,5.213,3.324,7.049,8.021v231.248
c-8.989,0.339-16.203,7.737-16.203,16.808c0,7.593,5.054,14.021,11.973,16.115c0.516,0.346,1.097,0.601,1.734,0.709
c0.462,0.65,1.271,2.523,1.271,5.461c0,2.86-0.764,4.7-1.231,5.396h-7.371c-9.286,0-16.84,7.555-16.84,16.84v10.397
c0,2.831,0.709,5.496,1.948,7.84h-17.983c-2.485,0-4.5,2.015-4.5,4.5v22.856c0,2.485,2.015,4.5,4.5,4.5h180.043
c2.485,0,4.5-2.015,4.5-4.5v-22.856c0-2.485-2.015-4.5-4.5-4.5h-17.983c1.239-2.344,1.948-5.009,1.948-7.84v-10.397
c0-9.285-7.554-16.84-16.84-16.84h-7.378c-0.467-0.695-1.231-2.536-1.231-5.396c0-2.938,0.809-4.811,1.272-5.461
c0.635-0.108,1.215-0.362,1.73-0.706c6.924-2.091,11.982-8.523,11.982-16.119c0-9.07-7.214-16.468-16.203-16.807V82.78
C261.881,78.069,265.104,75.772,267.087,74.755z M251.543,8.966c-1.168,0.684-2.352,1.397-3.565,2.165
c-14.149,8.949-21.986,10.399-35.251,10.401c-13.265-0.002-21.103-1.452-35.252-10.401c-1.213-0.768-2.397-1.481-3.565-2.165
H251.543z M298.247,416.45H127.204v-13.856h171.043V416.45z M269.872,367.517c4.323,0,7.84,3.517,7.84,7.84v10.397
c0,4.323-3.517,7.84-7.84,7.84H155.579c-4.323,0-7.84-3.517-7.84-7.84v-10.397c0-4.323,3.517-7.84,7.84-7.84H269.872z
 M252.888,358.517h-80.335c0.403-1.644,0.627-3.454,0.627-5.396c0-1.961-0.228-3.788-0.638-5.446h80.361
c-0.411,1.658-0.641,3.484-0.641,5.446C252.263,355.063,252.486,356.873,252.888,358.517z M267.247,330.835
c0,4.323-3.517,7.84-7.84,7.84h-93.363c-4.323,0-7.84-3.517-7.84-7.839c0-4.323,3.517-7.84,7.84-7.84h93.363
C263.73,322.996,267.247,326.513,267.247,330.835z M230.999,91.564c-7.029,0-12.748,5.719-12.748,12.747v209.686h-11.049V104.311
c0-7.028-5.719-12.747-12.748-12.747c-7.029,0-12.748,5.719-12.748,12.747v209.686h-7.299V86.709h76.637v227.287h-7.297V104.311
C243.747,97.282,238.028,91.564,230.999,91.564z M234.747,104.311v209.686h-7.496V104.311c0-2.066,1.681-3.747,3.748-3.747
S234.747,102.244,234.747,104.311z M198.202,104.311v209.686h-7.496V104.311c0-2.066,1.681-3.747,3.748-3.747
C196.521,100.564,198.202,102.244,198.202,104.311z M173.017,77.709c-0.624-1.304-1.32-2.479-2.061-3.533h83.538
c-0.741,1.055-1.438,2.229-2.061,3.533H173.017z M169.114,65.176c3.029-3.876,5.28-8.272,6.475-12.975h74.275
c1.195,4.703,3.445,9.1,6.475,12.975H169.114z M258.043,47.153c0-0.003-0.001-0.005-0.001-0.008c0-0.003,0-0.007,0-0.01
c-0.865-6.827,2.838-15.029,6.702-18.12c7.771-6.216,18.431-5.704,25.349,1.212c5.059,5.06,5.059,13.29,0,18.35
c-3.695,3.695-9.71,3.695-13.405,0c-2.606-2.606-2.606-6.847,0-9.453c1.733-1.732,4.555-1.732,6.288,0
c1.758,1.758,4.607,1.758,6.364,0c1.757-1.757,1.757-4.606,0-6.363c-5.243-5.244-13.773-5.244-19.017,0
c-6.115,6.115-6.115,16.065,0,22.18c3.49,3.49,8.131,5.412,13.067,5.412c4.936,0,9.577-1.922,13.067-5.412
c8.568-8.567,8.568-22.509-0.001-31.077c-10.219-10.217-25.921-11.006-37.335-1.876c-5.598,4.479-9.559,13.108-10.121,21.214h-72.55
c-0.563-8.107-4.524-16.736-10.122-21.214c-11.414-9.132-27.115-8.342-37.335,1.877c-8.568,8.567-8.568,22.509,0,31.076
c3.49,3.49,8.131,5.412,13.067,5.412c4.936,0,9.577-1.922,13.067-5.412c6.115-6.115,6.115-16.064,0-22.18
c-5.243-5.244-13.773-5.244-19.017,0c-1.757,1.757-1.757,4.607,0,6.363c1.758,1.758,4.607,1.758,6.364,0
c1.733-1.732,4.555-1.732,6.288,0c2.606,2.607,2.606,6.847,0,9.453c-3.695,3.695-9.71,3.695-13.405,0
c-5.059-5.06-5.059-13.29,0-18.349c6.919-6.919,17.58-7.429,25.349-1.214c3.864,3.091,7.567,11.294,6.704,18.122
c-0.001,0.003,0,0.006-0.001,0.009c0,0.003-0.001,0.005-0.001,0.008c-1.653,13.478-15.724,24.863-30.725,24.863
c-17.383,0-31.525-14.143-31.525-31.525c0-17.37,14.122-31.503,31.487-31.524h9.869c7.874,0.301,15.941,3.315,26.148,9.77
c15.835,10.017,25.536,11.79,40.03,11.796h0.066c14.494-0.006,24.195-1.779,40.03-11.796c10.205-6.456,18.272-9.47,26.146-9.77
h9.869c17.365,0.021,31.487,14.154,31.487,31.524c0,17.383-14.142,31.525-31.525,31.525
C273.766,72.016,259.696,60.63,258.043,47.153z'/>
</svg>"""

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
path {
  fill: rgb(35, 63, 51);
}"""

    html_template = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="ie=edge">
    <link rel="icon" href="data:image/svg+xml;utf8,{svg_icon}" />
    <title>Alexandria - Welcome</title>
    <style>
    {css}
    </style>
  </head>
  <body>
    <main>
        <h1>Welcome to Alexandria{svg_logo}</h1>
        <h2>Your personal library from internet</h2>

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
  </body>
</html>"""

    def log_message(self, fmt, *args):
        if DEBUG:
            return super().log_message(fmt, *args)

    def response(self, status_code, **context):
        template = self.html_template.format(css=self.css, svg_icon=self.svg_icon, svg_logo=self.svg_logo, **context)

        self.send_response(status_code)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(bytes(template, "utf-8"))

    def do_GET(self):
        url = urlparse(self.path)

        if url.path == "/":
            mirrors_table = MirrorsFile(DATABASE).to_html()
            return self.response(200, table=mirrors_table)
        return super().do_GET()

def humanize_size(num):
    units = ("KiB", "MiB", "GiB")
    limit_to_nex_unit = 1000
    for u in units:
        num /= KB
        if num > limit_to_nex_unit:
            continue
        break
    return "{num:3.1f} {u} ".format(num = num, u = u)

def humanize_url(url):
    if len(url) > MAX_TRUNC:
        url = url[:MAX_TRUNC] + "(...)"

    return url.removeprefix("https://").removeprefix("http://").removeprefix("www.")

def humanize_datetime(dt):
    return dt.strftime(DATETIME_FMT)

class WebsiteMirror:
    title_re = re.compile(r"<title.*?>(.+?)</title>", flags=re.IGNORECASE)

    def __init__(self, url, created_at=None):
        self.url = url
        self.path = self.path_from_url(url)
        self.title = self.grep_title_from_file()
        self.size = self.calculate_size_disk(self.path.split("/")[0])

        if created_at is None:
            debug_print(f"Generated - {self.url}")
            self.created_at = datetime.now()
        else:
            debug_print(f"Reloaded - {self.url}")
            self.created_at = created_at

    def __hash__(self):
        return hash(self.url)

    def __eq__(self, other):
        return other.url == self.url

    def __repr__(self):
        return f"<Mirror url={self.url}>"

    def __str__(self):
        return self.url

    @classmethod
    def from_mirror(cls, other):
        # Re-crate mirror from other mirror
        return cls(other.url, other.created_at)

    def path_from_url(self, url):
        url = urlparse(url)
        path = MIRRORS_PATH + url.netloc + url.path

        if path[-1] == "/":
            path = path[:-1]

        matches_files = ["", ".html", "/index.html", ("/index.html@" + url.query + ".html")]
        possibles_files = [Path(path + p) for p in matches_files]
        for f in possibles_files:
            if f.is_file():
                return str(f)
        assert False,( "unreachable - cound not determinate the html file!\n"
                       "check there is any option available: \n" +
                       "\n".join(str(p) for p in possibles_files))

    def grep_title_from_file(self):
        file_text = ""
        with open(self.path, "r") as f:
            for l in f.readlines():
                file_text += l
                f = self.title_re.search(file_text)
                if f:
                    return html.unescape(f.groups()[0])
        assert False, (f"unreachable - do not found <title> in the html\n"
                       f"-> {self.url} NEED be a staticpage!")

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
        url = humanize_url(self.url)
        return f"""<tr>
            <td><a href="{self.path}">{url}</a></td>
            <td>{self.title}</td>
            <td>{humanize_size(self.size)}</td>
            <td>{humanize_datetime(self.created_at)}</td>
            </tr>"""

    def to_md(self):
        return f"[{self.title}]({self.url})\n_{self.created_at.strftime(DATETIME_FMT)}_"

class MirrorsFile():
    default = list

    def __init__(self, path):
        self.path = path
        self.initial_migration_if_need(path)

        with open(path, "rb") as f:
            mirrors_file = pickle.load(f)

        self.data = self.default()
        for mirror in mirrors_file:
            self.add(WebsiteMirror.from_mirror(mirror))
        debug_print(f"MirrorsFile loaded! -  total: {len(self.data)}")

    def __iter__(self):
        return self.data.__iter__()

    @classmethod
    def initial_migration_if_need(cls, path):
        file_disk = Path(path)
        if not file_disk.exists():
            self.save(cls.default())
            debug_print("Initial migration done!")

    def to_html(self):
        return " ".join(m.to_html() for m in self.data)

    def to_md(self):
        today = datetime.now()
        md_body = "\n\n".join(m.to_md() for m in self.data)
        return "# Alexandria - generated at {}\n{}".format(today.strftime(DATETIME_FMT), md_body)

    def add(self, mr):
        if mr not in self.data:
            self.data.append(mr)
        else:
            title_print(f"Skip add {mr.url}, already in")

    def save(self, data=None):
        if not data:
            # keeps its overwriting, redo keeping writing and append if it get wrost
            data = self.data

        debug_print("Saving mirrors-list on disk...")
        with open(self.path, "wb") as f:
            pickle.dump(data, f, pickle.HIGHEST_PROTOCOL)

def serve(port):
    server = HTTPServerAlexandria
    title_print(f"Start server at {port}")
    title_print(LINK_MASK.format(f"http://localhost:{port}", f"http://localhost:{port}"))

    with HTTPServer(("", port), server) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.server_close()
            title_print(f"Alexandria server:{port} ended!")
            sys.exit(EXIT_SUCCESS)

def process_download(url):
    urlp = urlparse(url)
    if not bool(urlp.scheme):
        title_print(f"Not valid url - {url}")
        sys.exit(EXIT_SUCCESS)

    domain = urlp.hostname
    title_print(f"Making a mirror of: {url} at {domain}")

    wget_process = (f"wget"
                    f" -P {MIRRORS_PATH}"
                    f" --mirror -p --recursive -l 1 --page-requisites --adjust-extension --span-hosts"
                    f" -U 'Mozilla' -E -k"
                    f" -e robots=off --random-wait --no-cookies"
                    f" --convert-links --restrict-file-names=windows --domains {domain}"
                    f" --no-parent {url}".split(" "))

    debug_print("command: {}".format(" ".join(wget_process)))
    subprocess.run(wget_process, check=False)
    title_print(f"Finished {url}!!!")

def generate_md_database(content):
    with open(DATABASE_README, "wb") as f:
        f.write(bytes(content, "utf-8"))
    debug_print(f"Database {DATABASE_README} generated...")

if __name__ == "__main__":
    title_print("Alexandria")

    args = parser.parse_args()
    website = args.website
    port = int(args.port)
    DEBUG = args.verbose
    skip = args.skip

    # server it - bye!
    if not website:
        serve(port)
        sys.exit(EXIT_SUCCESS)

    if skip and DEBUG:
        debug_print("BYPASSING THE PROCESS OF DOWNLOAD - you are on your own", border=True)
    else:
        process_download(website)
    mirror = WebsiteMirror(website)

    mirrors = MirrorsFile(DATABASE)
    mirrors.add(mirror)
    mirrors.save()
    generate_md_database(mirrors.to_md())
