"""A deliberately faulty CSV reader for a reproducible, labelled demo.

Writes to a new output directory. No network access, deletion or personal input.
ReproLens itself never executes submitted code. This lab is run separately.
"""
import argparse
import csv
import io
import json
import platform
import sys
from decimal import Decimal
from pathlib import Path


def total(path):
    # Deliberate fixture defect: utf-8 preserves a BOM in the first field name.
    with path.open(encoding='utf-8', newline='') as stream:
        return sum(Decimal(row['amount']) for row in csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    data = 'amount,item\n10.00,notebook\n2.50,pencil\n'
    (args.output/'plain.csv').write_text(data, encoding='utf-8', newline='')
    (args.output/'excel.csv').write_text(data, encoding='utf-8-sig', newline='')
    observations = []
    for name in ['plain.csv','excel.csv']:
        try:
            observations.append(f'{name}: total = {total(args.output/name)}')
        except Exception as error:
            observations.append(f'{name}: {type(error).__name__}: {error}')
    log = '\n'.join(observations) + '\n'
    (args.output/'observed.log').write_text(log, encoding='utf-8')
    environment = f'Python {platform.python_version()} on {platform.system()} {platform.release()}\nOnly the Python standard library is used.\n'
    (args.output/'environment.txt').write_text(environment, encoding='utf-8')
    notes = ('The two CSV files contain the same two purchase rows.\n'
             'Run the provided CSV lab script to generate plain.csv and excel.csv.\n'
             'Read plain.csv using the supplied total() function.\n'
             'Read excel.csv using the same function.\n'
             'Both files should produce a total of 12.50.\n')
    (args.output/'steps.txt').write_text(notes, encoding='utf-8')
    (args.output/'receipt.json').write_text(json.dumps({'fixture':'deliberately faulty UTF-8 CSV reader','data':'synthetic purchase rows','actual_execution':True,'observations':observations,'environment':environment,'reprolens_executes_input':False},indent=2),encoding='utf-8')
    print(log,end='')


if __name__ == '__main__':
    main()
