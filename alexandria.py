import argparse
import html
import os
import pickle  # REVIEW move to json?
import re
import subprocess
import sys
from datetime import datetime
from functools import cached_property
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# NOTE TODO this is relative
ALEXANDRIA_PATH = "alx/"
DATABASE_PATH = ALEXANDRIA_PATH + "database"
DATABASE_README = ALEXANDRIA_PATH + "README.md"
MIRRORS_PATH = ALEXANDRIA_PATH + "mirrors/"
DEFAULT_PORT = 8000
DEBUG = False
EXIT_SUCCESS = 0
LINK_MASK = "\u001b]8;;{}\u001b\\{}\u001b]8;;\u001b\\"
MAX_TRUNC = 45


def from_static(name):
    return f"./static/{name}"


def sanitize_title(title):
    return title.replace("|", "-").replace("\n", "")


def sanitize_size(num):
    if num == 0:
        return "0 B"

    KiB = 1024
    units = ("KiB", "MiB", "GiB")
    for u in units:
        num /= KiB
        if abs(num) < KiB:
            break
    return f"{num:3.1f} {u}"


def sanitize_url(url):
    url = url.removeprefix("https://").removeprefix("http://").removeprefix("www.")
    if len(url) > MAX_TRUNC:
        url = url[:MAX_TRUNC] + "(...)"
    return url


def sanitize_datetime(dt):
    datetime_fmt = "%d. %B %Y %I:%M%p"
    return dt.strftime(datetime_fmt)


def border(msg):
    width = 25
    bordered_msg = "*" * width
    bordered_msg += f"\n{msg}\n"
    bordered_msg += "*" * width
    return bordered_msg


def debug_print(log, add_border=False):
    debug_msg = f"[DEBUG] {log}"
    if DEBUG:
        if add_border:
            debug_msg = border(debug_msg)
        print(debug_msg)
    return debug_msg


def title_print(title):
    border_print = "*" * 8
    title_msg = "\n" + border_print + f" {title} " + border_print
    print(title_msg)
    return title_msg


class HTTPServerAlexandria(SimpleHTTPRequestHandler):
    server_version = "HTTPServerAlexandria"
    template_name = from_static("index.html")
    stylesheet = from_static("index.css")

    @cached_property
    def html_template(self):
        with open(self.template_name, "r") as f:
            return f.read()

    def log_message(self, fmt, *args):
        if DEBUG:
            return super().log_message(fmt, *args)

    def response_index(self, status_code, **context):
        template = self.html_template.format(css=self.stylesheet, **context)

        self.send_response(status_code)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(bytes(template, "utf-8"))

    def do_GET(self):
        url = urlparse(self.path)

        if url.path == "/":
            database = Database(DATABASE_PATH)
            return self.response_index(200, table=database.to_html())
        return super().do_GET()


class Webpage:
    title_re = re.compile(r"<title.*?>(.+?)</title>", flags=re.IGNORECASE | re.DOTALL)

    def __init__(self, url, created_at=None):
        self.url = url
        self.base_path, self.full_path = self.index_path(url)
        self.title = self.grep_title_from_index()
        self.size = self.calculate_size_disk(self.base_path)

        if created_at is None:
            debug_print(f"[GENERATED] {self!r}")
            self.created_at = datetime.now()
        else:
            debug_print(f"[RELOADED] {self!r}")
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
    def from_webpage(cls, other):
        # Re-crate mirror from other mirror - migrate
        return cls(other.url, other.created_at)

    def index_path(self, url):
        url = urlparse(url)
        path = MIRRORS_PATH + url.netloc + url.path
        if path[-1] == "/":
            path = path[:-1]

        matches_files = ["", ".html", "/index.html", ("/index.html@" + url.query + ".html")]
        possibles_files = [Path(path + p) for p in matches_files]
        for f in possibles_files:
            if f.is_file():
                return (MIRRORS_PATH + url.netloc), str(f)
        # TODO move to a exception
        assert False, ("unreachable - cound not determinate the html file!\n"
                       "check there is any option available: \n") + "\n".join(str(p) for p in possibles_files)

    def grep_title_from_index(self):
        file_text = ""
        with open(self.full_path, "r") as f:
            for line in f.readlines():
                file_text += line
                f = self.title_re.search(file_text)
                if f:
                    return html.unescape(f.groups()[0])
        # TODO move to a exception
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
        title = sanitize_title(self.title)
        url = sanitize_url(self.url)
        full_path = self.full_path
        size = sanitize_size(self.size)
        created_at = sanitize_datetime(self.created_at)
        return f"""<tr>
            <td class="td_title">{title}</td>
            <td><a href="{full_path}">{url}</a></td>
            <td>{size}</td>
            <td>{created_at}</td>
            </tr>"""

    def to_md_line(self):
        title = sanitize_title(self.title)
        url = self.url
        created_at = sanitize_datetime(self.created_at)
        return f"| [{title}]({url}) | {created_at} |"


class Database():
    export_file = DATABASE_README

    def __init__(self, path):
        self.path = path
        self.data = []
        self.initial_migration_if_need(path)

        with open(path, "rb") as f:
            db_file = pickle.load(f)

        for entry in db_file:
            self.add(Webpage.from_webpage(entry))
        debug_print(f"Database loaded! - total: {len(self.data)}")

    def __iter__(self):
        return self.data.__iter__()

    def initial_migration_if_need(self, path):
        file_disk = Path(path)

        if not file_disk.exists():
            file_disk.parent.mkdir(exist_ok=True, parents=True)
            self.save(self.data)
            debug_print("Initial migration done!")

    def to_html(self):
        table = """<table>
          <tr>
            <th>Title</th>
            <th>URL</th>
            <th>Size</th>
            <th>Created at</th>
          </tr>\n"""

        return table + " ".join(m.to_html() for m in self.data[::-1])

    def to_md(self):
        today = sanitize_datetime(datetime.now())
        md_body = "\n".join(site.to_md_line() for site in self.data[::-1])
        return (f"# Alexandria - generated at {today}\n"
                f"| Site | Created at |\n"
                f"| ---- | ---------- |\n"
                f"{md_body}\n")

    def add(self, mr):
        if mr not in self.data:
            self.data.append(mr)
        else:
            title_print(f"Skip add {mr.url}, already in")

    def save(self, data=None):
        if data is None:
            data = self.data

        debug_print("Saving mirrors-list on disk...")
        with open(self.path, "wb") as f:
            # keeps its overwriting, redo keeping writing and append if it get wrost
            pickle.dump(data, f, pickle.HIGHEST_PROTOCOL)
        debug_print("Saved.")

        with open(self.export_file, "wb") as f_export:
            f_export.write(bytes(self.to_md(), "utf-8"))
        debug_print(f"Database {DATABASE_README} generated.")


# NOTE Compatibility mode - will drop soon
class WebsiteMirror(Database):
    pass
class WebPage(Webpage):
    pass


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

    parser = argparse.ArgumentParser(prog="Alexandria", description="A tool to manage your personal website backup libary", epilog="Keep and hold")
    parser.add_argument("website", help="One or more internet links (URL)", nargs="*")
    parser.add_argument("-p", "--port", help="The port to run server, 8000 is default", default=DEFAULT_PORT, type=int)
    parser.add_argument("-v", "--verbose", help="Enable verbose", default=DEBUG, action=argparse.BooleanOptionalAction, type=bool)
    parser.add_argument("-s", "--skip", help="Skip download process, only add entry.", default=False, action=argparse.BooleanOptionalAction, type=bool)
    parser.add_argument("--readme", "--database-readme", help="Generate the database README.", default=False, action=argparse.BooleanOptionalAction, type=bool)
    args = parser.parse_args()

    websites = args.website
    port = int(args.port)
    skip = args.skip
    generate_readme = args.readme
    DEBUG = args.verbose

    database = Database(DATABASE_PATH)
    if DEBUG and generate_readme:
        generate_md_database(database.to_md())
        sys.exit(EXIT_SUCCESS)

    # server it - bye!
    if not websites:
        serve(port)
        sys.exit(EXIT_SUCCESS)

    if skip and DEBUG:
        debug_print("BYPASSING THE PROCESS OF DOWNLOAD - you are on your own", border=True)
    else:
        for website in websites:
            process_download(website)
            webpage = WebPage(website)
            database.add(webpage)

    database.save()
    generate_md_database(database.to_md())
