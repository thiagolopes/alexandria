# Alexandria
Create your personal backup from Internet

![image](https://github.com/thiagolopes/alexandria/assets/5994972/642f4c31-8253-46ef-bcd7-d347c6cee742)

## How to install
```
git clone https://github.com/thiagolopes/alexandria
cd alexandria
pip install .
```

## How to run:
To run the server:
```
python -m alexandria
```
Will run at default port (8000)

To download new site:
```
python -m alexandria.py https://bin.com/index.html
```
And the new site will be available in database and server instance.

## Requirements
- `wget`
- `python >= 3.10`

## About
This project aim to be one file only and minimal deps as possible

## References

- [Python 3 - Pickle Doc](https://docs.python.org/3/library/pickle.html)
- [Python 3 - Unittest](https://docs.python.org/3/library/unittest.html)
- [Python 3 - Tempfile](https://docs.python.org/3/library/tempfile.html)
