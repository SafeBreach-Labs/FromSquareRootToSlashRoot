import os

def ParseMetadata(data):
    name = None
    version = None
    summary = None
    for line in data.splitlines():
        if line.startswith("Name: "):
            name = line[6:].strip()
        elif line.startswith("Version: "):
            version = line[9:].strip()
        elif line.startswith("Summary: "):
            summary = line[9:].strip()
        if name and version and summary:
            return name, version, summary
    return None, None, None


packages = {}
for root,dirs,files in os.walk('/app/officepy/lib/python3.12/site-packages'):
    for f in files:
        if not f.endswith('METADATA'):
            continue

        text = open(os.path.join(root,f), 'rb').read().decode("utf-8", errors="ignore")
        name, version, summary = ParseMetadata(text)
        if name and version and summary:
            packages[name] = f"{version};{summary}"

s = sorted(packages.items())
print("sep=;")
for name, version in s:
    print(f"{name};{version}")