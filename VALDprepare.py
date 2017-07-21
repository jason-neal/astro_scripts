#!/usr/bin/env python
# -*- coding: utf8 -*-

# My imports
import argparse
import gzip


def _parser():
    parser = argparse.ArgumentParser(description='Prepare the data downloaded '
                                     'from VALD.')
    parser.add_argument('input', help='input compressed file')
    parser.add_argument('-o', '--output',
                        help='Optional output',
                        default=False)
    return parser.parse_args()


def main(input, output=False):
    if not isinstance(input, str):
        raise TypeError('Input must be a str. A {0!s} was parsed'.format(type(input)))
    if not isinstance(output, str) and output:
        raise TypeError('Output must be a str. A {0!s} was parsed'.format(type(output)))

    # TODO: Check if the input exists

    fname = input.rpartition('.')[0]
    if not output:
        output = '{0!s}.dat'.format(fname)
    oref = '{0!s}.ref'.format(fname)

    fout = ''
    fref = ''
    with gzip.open(input, 'r') as lines:
        for i, line in enumerate(lines):
            if i < 2:
                fout += '# {0!s}'.format(line.replace("'", ''))
            else:
                fout += line.replace("'", '')
            if 'References' in line:
                break

    with open(output, 'w') as fo:
        fo.write(fout)


if __name__ == '__main__':
    args = _parser()
    input, output = args.input, args.output
    main(input, output)
