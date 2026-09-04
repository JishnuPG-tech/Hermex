import re
import sys

def find_strings(path):
    with open(path, 'rb') as f:
        data = f.read()
    # Find sequence of printable characters
    strings = re.findall(rb'[ -~]{4,}', data)
    for s in strings:
        print(s.decode('utf-8'))

if __name__ == "__main__":
    find_strings(sys.argv[1])
