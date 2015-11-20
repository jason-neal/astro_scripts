#!/usr/bin/env python
# -*- coding: utf8 -*-

# My imports
from __future__ import division, print_function
import os
import urllib
import numpy as np
import scipy.interpolate as sci
import matplotlib.pyplot as plt
import matplotlib
from astropy.io import fits
from astropy.modeling import models, fitting
import argparse
from gooey import Gooey, GooeyParser


def _download_spec(fout):
    """
    Download a spectrum from my personal web page
    """
    import requests
    spec = fout.rpartition('/')[-1]
    url = 'http://www.astro.up.pt/~dandreasen/%s' % spec
    spectrum = requests.get(url)
    with open(fout, 'w') as file:
        file.write(spectrum.content)


class Cursor:
    """Get a crosshair at the cursor's position

    The code is from here:
    http://matplotlib.org/examples/pylab_examples/cursor_demo.html
    """

    def __init__(self, ax):
        self._ax = ax
        self.lx = ax.axhline(color='b', lw=2, alpha=0.7)
        self.ly = ax.axvline(color='b', lw=2, alpha=0.7)

    def mouse_move(self, event):
        if not event.inaxes:
            return
        x, y = event.xdata, event.ydata
        self.lx.set_ydata(y)
        self.ly.set_xdata(x)
        plt.draw()


def ccf_astro(spectrum1, spectrum2, rvmin=0, rvmax=200, drv=1):
    """Make a CCF between 2 spectra and find the RV

    :spectrum1: The stellar spectrum
    :spectrum2: The model, sun or telluric
    :dv: The velocity step
    :returns: The RV shift
    """

    # Calculate the cross correlation
    s = False
    w, f = spectrum1
    tw, tf = spectrum2
    if not len(w) or not len(tw):
        return 0, 0, 0, 0, 0
    c = 299792.458
    drvs = np.arange(rvmin, rvmax, drv)
    cc = np.zeros(len(drvs))
    for i, rv in enumerate(drvs):
        fi = sci.interp1d(tw * (1.0 + rv / c), tf)
        # Shifted template evaluated at location of spectrum
        try:
            fiw = fi(w)
            cc[i] = np.sum(f * fiw)
        except ValueError:
            s = True
            fiw = 0
            cc[i] = 0

    if s:
        print('Warning: Lower the bounds on RV')

    if not np.any(cc):
        return 0, 0, 0, 0, 0

    # Fit the CCF with a gaussian
    cc[cc == 0] = np.mean(cc)
    cc = (cc-min(cc))/(max(cc)-min(cc))
    RV, g = _fit_ccf(drvs, cc)
    return int(RV), drvs, cc, drvs, g(drvs)


def _fit_ccf(rv, ccf):
    """Fit the CCF with a 1D gaussian
    :rv: The RV vector
    :ccf: The CCF values
    :returns: The RV, and best fit gaussian

    """
    ampl = 1
    mean = rv[ccf == ampl]
    I = np.where(ccf == ampl)[0]

    g_init = models.Gaussian1D(amplitude=ampl, mean=mean, stddev=5)
    fit_g = fitting.LevMarLSQFitter()

    try:
        g = fit_g(g_init, rv[I - 10:I + 10], ccf[I - 10:I + 10])
    except TypeError:
        print('Warning: Not able to fit a gaussian to the CCF')
        return 0, g_init
    RV = g.mean.value
    return RV, g


def nrefrac(wavelength, density=1.0):
    """Calculate refractive index of air from Cauchy formula. Input:
    wavelength in Angstrom, density of air in amagat (relative to STP,
    e.g. ~10% decrease per 1000m above sea level). Returns N = (n-1) *
    1.e6.

    The IAU standard for conversion from air to vacuum wavelengths is given
    in Morton (1991, ApJS, 77, 119). For vacuum wavelengths (VAC) in
    Angstroms, convert to air wavelength (AIR) via:

    AIR = VAC / (1.0 + 2.735182E-4 + 131.4182 / VAC^2 + 2.76249E8 / VAC^4)
    """
    wl = np.array(wavelength)

    wl2inv = (1.e4 / wl) ** 2
    refracstp = 272.643 + 1.2288 * wl2inv + 3.555e-2 * wl2inv ** 2
    return density * refracstp


def dopplerShift(wvl, flux, v, edgeHandling='firstlast', fill_value=None):
    """Doppler shift a given spectrum.
    This code is taken from the PyAstronomy project:
    https://github.com/sczesla/PyAstronomy
    All credit to the author.

    A simple algorithm to apply a Doppler shift
    to a spectrum. This function, first, calculates
    the shifted wavelength axis and, second, obtains
    the new, shifted flux array at the old, unshifted
    wavelength points by linearly interpolating.

    Due to the shift, some bins at the edge of the
    spectrum cannot be interpolated, because they
    are outside the given input range. The default
    behavior of this function is to return numpy.NAN
    values at those points. One can, however, specify
    the `edgeHandling` parameter to choose a different
    handling of these points.

    If "firstlast" is specified for `edgeHandling`,
    the out-of-range points at the red or blue edge
    of the spectrum will be filled using the first
    (at the blue edge) and last (at the red edge) valid
    point in the shifted, i.e., the interpolated, spectrum.

    If "fillValue" is chosen for edge handling,
    the points under consideration will be filled with
    the value given through the `fillValue` keyword.

    .. warning:: Shifting a spectrum using linear
                interpolation has an effect on the
                noise of the spectrum. No treatment
                of such effects is implemented in this
                function.

    Parameters
    ----------
    wvl : array
        Input wavelengths in A.
    flux : array
        Input flux.
    v : float
        Doppler shift in km/s
    edgeHandling : string, {"fillValue", "firstlast"}, optional
        The method used to handle the edges of the
        output spectrum.
    fillValue : float, optional
        If the "fillValue" is specified as edge handling method,
        the value used to fill the edges of the output spectrum.

    Returns
    -------
    nflux : array
        The shifted flux array at the *old* input locations.
    wlprime : array
        The shifted wavelength axis.
    """

    # Shifted wavelength axis
    wlprime = wvl * (1.0 + v / 299792.458)

    f = sci.interp1d(wlprime, flux, bounds_error=False, fill_value=np.nan)
    nflux = f(wlprime)

    if edgeHandling == "firstlast":
        firsts = []
        # Search for first non-NaN value save indices of
        # leading NaN values
        for i, nfluxi in enumerate(nflux):
            if np.isnan(nfluxi):
                firsts.append(i)
            else:
                firstval = nfluxi
                break

        # Do the same for trailing NaNs
        lasts = []
        for i, nfluxi in enumerate(nflux[::-1]):
            if np.isnan(nfluxi):
                lasts.append(i)
            else:
                lastval = nfluxi
                break

        # Use first and last non-NaN value to
        # fill the nflux array
        if fill_value:
            nflux[firsts] = fill_value
            nflux[lasts] = fill_value
        else:
            nflux[firsts] = firstval
            nflux[lasts] = lastval
    return nflux, wlprime


def get_wavelength(hdr):
    """Return the wavelength vector calculated from the header of a FITS
    file.

    :hdr: Header from a FITS ('CRVAL1', 'CDELT1', and 'NAXIS1' is required as
            keywords)
    :returns: Equidistant wavelength vector

    """
    w0, dw, n = hdr['CRVAL1'], hdr['CDELT1'], hdr['NAXIS1']
    w1 = w0 + dw * n
    return np.linspace(w0, w1, n, endpoint=False)


@Gooey(program_name='Plot fits - Easy 1D fits plotting', default_size=(610, 730))
def _parser():
    """Take care of all the argparse stuff.

    :returns: the args
    """
    parser = GooeyParser(description='Plot 1D fits files with wavelength information in the header.')
    parser.add_argument('fname',
                        action='store',
                        widget='FileChooser',
                        help='Input fits file')
    parser.add_argument('-m', '--model',
                        default=False,
                        widget='FileChooser',
                        help='If not the Sun shoul be used as a model, put'
                        ' the model here (only support BT-Settl for the'
                        ' moment)',)
    parser.add_argument('-s', '--sun',
                        help='Over plot solar spectrum',
                        action='store_true')
    parser.add_argument('-t', '--telluric',
                        help='Over plot telluric spectrum',
                        action='store_true')
    parser.add_argument('-r', '--rv',
                        help='RV shift to observed spectra in km/s',
                        default=False,
                        type=float)
    parser.add_argument('-r1', '--rv1',
                        help='RV shift to model/solar spectrum in km/s',
                        default=False,
                        type=float)
    parser.add_argument('-r2', '--rv2',
                        help='RV shift to telluric spectra in km/s',
                        default=False,
                        type=float)
    parser.add_argument('-l', '--lines',
                        help='Lines to plot on top (multiple lines is an'
                        ' option). If multiple lines needs to be plotted, then'
                        ' separate with a space',
                        default=False,
                        nargs='+',
                        type=float)
    parser.add_argument('-c', '--ccf',
                        default='none',
                        choices=['none', 'sun', 'model', 'telluric', 'both'],
                        help='Calculate the CCF for Sun/model or tellurics '
                        'or both.')
    parser.add_argument('--ftype', help='Select which type the fits file is',
                        choices=['1D', 'CRIRES', 'GIANO'], default='1D')
    parser.add_argument('--fitsext', help='Select fits extention, Default 0.',
                        choices=['0', '1', '2', '3', '4'], default='0')
    parser.add_argument('--order', help='Select which GIANO order to be investigated',
                        choices=map(str, range(32,81)), default='77')
    return parser.parse_args()


def main(fname, lines=False, model=False, telluric=False, sun=False,
         rv=False, rv1=False, rv2=False, ccf='none', ftype='1D',
         fitsext='0', order='77'):
    """Plot a fits file with extensive options

    :fname: Input spectra
    :lines: Absorption lines
    :model: Model spectrum
    :telluric: Telluric spectrum
    :sun: Solar spectrum
    :rv: RV of input spectrum
    :rv1: RV of Solar/model spectrum
    :rv2: RV of telluric spectrum
    :ccf: Calculate CCF (sun, model, telluric, both)
    :ftype: Type of fits file (1D, CRIRES, GIANO)
    :fitsext: Slecet fits extention to use (0,1,2,3,4)
    :returns: RV if CCF have been calculated
    """
    print('\n-----------------------------------')
    path = os.path.expanduser('~/.plotfits/')
    pathsun = os.path.join(path, 'solarspectrum_01.fits')
    pathtel = os.path.join(path, 'telluric_NIR.fits')
    pathwave = os.path.join(path, 'WAVE_PHOENIX-ACES-AGSS-COND-2011.fits')
    pathGIANO = os.path.join(path, 'wavelength_GIANO.dat')
    if os.path.isdir(path):
        if sun and (not os.path.isfile(pathsun)):
            print('Downloading solar spectrum...')
            _download_spec(pathsun)
        if telluric and (not os.path.isfile(pathtel)):
            print('Downloading telluric spectrum...')
            _download_spec(pathtel)
        if model and (not os.path.isfile(pathwave)):
            print('Downloading wavelength vector for model...')
            url = 'ftp://phoenix.astro.physik.uni-goettingen.de/HiResFITS//WAVE_PHOENIX-ACES-AGSS-COND-2011.fits'
            urllib.urlretrieve(url, pathwave)
    else:
        os.mkdir(path)
        print('%s Created' % path)
        print('Downloading solar spectrum...')
        _download_spec(pathsun)
        print('Downloading telluric spectrum...')
        _download_spec(pathtel)

    fitsext = int(fitsext)
    order = int(order)

    if ftype == '1D':
        I = fits.getdata(fname, fitsext)
        hdr = fits.getheader(fname, fitsext)
        w = get_wavelength(hdr)
    elif ftype == 'CRIRES':
        d = fits.getdata(fname, fitsext)
        hdr = fits.getheader(fname, fitsext)
        try:
            I = d['Extracted_OPT'] # Gasgano reduction
        except:
            I = d['Extracted_DRACS'] # Dracs reduction
        w = d['Wavelength']*10
    elif ftype == 'GIANO':
        d = fits.getdata(fname)
        I = d[order - 32]  # 32 is the first order
        wd = np.loadtxt(pathGIANO)
        w1, w2 = wd[wd[:, 0] == order][0][1:]
        w = np.linspace(w1, w2, len(I))

    I /= np.median(I)
    # Normalization (use first 50 points below 1.2 as constant continuum)
    maxes = I[(I < 1.2)].argsort()[-50:][::-1]
    I /= np.median(I[maxes])
    dw = 10  # Some extra coverage for RV shifts

    if rv:
        I, w = dopplerShift(wvl=w, flux=I, v=rv, fill_value=0.95)
    w0, w1 = w[0] - dw, w[-1] + dw

    if sun and not model:
        I_sun = fits.getdata(pathsun)
        hdr = fits.getheader(pathsun)
        w_sun = get_wavelength(hdr)
        i = (w_sun > w0) & (w_sun < w1)
        w_sun = w_sun[i]
        I_sun = I_sun[i]
        if len(w_sun) > 0:
            I_sun /= np.median(I_sun)
            if ccf in ['sun', 'both'] and rv1:
                print('Warning: RV set for Sun. Calculate RV with CCF')
            if rv1 and ccf not in ['sun', 'both']:
                I_sun, w_sun = dopplerShift(wvl=w_sun, flux=I_sun, v=rv1, fill_value=0.95)
        else:
            print('Warning: Solar spectrum not available in wavelength range.')
            sun = False
    elif sun and model:
        print('Warning: Both solar spectrum and a model spectrum are selected. Using model spectrum.')
        sun = False

    if model:
        I_mod = fits.getdata(model)
        hdr = fits.getheader(model)
        if 'WAVE' in hdr.keys():
            w_mod = fits.getdata(pathwave)
        else:
            w_mod = get_wavelength(hdr)
        nre = nrefrac(w_mod)  # Correction for vacuum to air (ground based)
        w_mod = w_mod / (1 + 1e-6 * nre)
        i = (w_mod > w0) & (w_mod < w1)
        w_mod = w_mod[i]
        I_mod = I_mod[i]
        if len(w_mod) > 0:
            # https://phoenix.ens-lyon.fr/Grids/FORMAT
            # I_mod = 10 ** (I_mod-8.0)
            I_mod /= np.median(I_mod)
            # Normalization (use first 50 points below 1.2 as continuum)
            maxes = I_mod[(I_mod < 1.2)].argsort()[-50:][::-1]
            I_mod /= np.median(I_mod[maxes])
            if ccf in ['model', 'both'] and rv1:
                print('Warning: RV set for model. Calculate RV with CCF')
            if rv1 and ccf not in ['model', 'both']:
                I_mod, w_mod = dopplerShift(wvl=w_mod, flux=I_mod, v=rv1, fill_value=0.95)
        else:
            print('Warning: Model spectrum not available in wavelength range.')
            model = False

    if telluric:
        I_tel = fits.getdata(pathtel)
        hdr = fits.getheader(pathtel)
        w_tel = get_wavelength(hdr)
        i = (w_tel > w0) & (w_tel < w1)
        w_tel = w_tel[i]
        I_tel = I_tel[i]
        if len(w_tel) > 0:
            I_tel /= np.median(I_tel)
            if ccf in ['telluric', 'both'] and rv2:
                print('Warning: RV set for telluric, Calculate RV with CCF')
            if rv2 and ccf not in ['telluric', 'both']:
                I_tel, w_tel = dopplerShift(wvl=w_tel, flux=I_tel, v=rv2, fill_value=0.95)
        else:
            print('Warning: Telluric spectrum not available in wavelength range.')
            telluric = False

    rvs = {}
    if ccf != 'none':
        if ccf in ['sun', 'both'] and sun:
            # remove tellurics from the Solar spectrum
            if telluric and sun:
                print('Correcting solar spectrum for tellurics...')
                I_sun = I_sun / I_tel
            print('Calculating CCF for the Sun...')
            rv1, r_sun, c_sun, x_sun, y_sun = ccf_astro((w, -I + 1), (w_sun, -I_sun + 1))
            if rv1 != 0:
                print('Shifting solar spectrum...')
                I_sun, w_sun = dopplerShift(w_sun, I_sun, v=rv1, fill_value=0.95)
                rvs['sun'] = rv1
                print('DONE')

        if ccf in ['model', 'both'] and model:
            print('Calculating CCF for the model...')
            rv1, r_mod, c_mod, x_mod, y_mod = ccf_astro((w, -I + 1), (w_mod, -I_mod + 1))
            if rv1 != 0:
                print('Shifting model spectrum...')
                I_mod, w_mod = dopplerShift(w_mod, I_mod, v=rv1, fill_value=0.95)
                rvs['model'] = rv1
                print('DONE')

        if ccf in ['telluric', 'both'] and telluric:
            print('Calculating CCF for the model...')
            rv2, r_tel, c_tel, x_tel, y_tel = ccf_astro((w, -I + 1), (w_tel, -I_tel + 1))
            if rv2 != 0:
                print('Shifting telluric spectrum...')
                I_tel, w_tel = dopplerShift(w_tel, I_tel, v=rv2, fill_value=0.95)
                rvs['telluric'] = rv2
                print('DONE')

    if len(rvs) == 0:
        ccf = 'none'

    if ccf != 'none':
        from matplotlib.gridspec import GridSpec
        fig = plt.figure(figsize=(16, 5))
        gs = GridSpec(1, 5)
        if len(rvs) == 1:
            gs.update(wspace=0.25, hspace=0.35, left=0.05, right=0.99)
            ax1 = plt.subplot(gs[:, 0:-1])
            ax2 = plt.subplot(gs[:, -1])
            ax2.set_yticklabels([])
        elif len(rvs) == 2:
            gs.update(wspace=0.25, hspace=0.35, left=0.01, right=0.99)
            ax1 = plt.subplot(gs[:, 1:4])
            ax2 = plt.subplot(gs[:, 0])
            ax3 = plt.subplot(gs[:, -1])
            ax2.set_yticklabels([])
            ax3.set_yticklabels([])
    else:
        fig = plt.figure(figsize=(16, 5))
        ax1 = fig.add_subplot(111)

    # Start in pan mode with these two lines
    manager = plt.get_current_fig_manager()
    manager.toolbar.pan()

    # Use nice numbers on x axis (y axis is normalized)...
    x_formatter = matplotlib.ticker.ScalarFormatter(useOffset=False)
    ax1.xaxis.set_major_formatter(x_formatter)

    if sun and not model:
        ax1.plot(w_sun, I_sun, '-g', lw=2, alpha=0.6, label='Sun')
    if telluric:
        ax1.plot(w_tel, I_tel, '-r', lw=2, alpha=0.5, label='Telluric')
    if model:
        ax1.plot(w_mod, I_mod, '-g', lw=2, alpha=0.5, label='Model')
    ax1.plot(w, I, '-k', lw=2, label='Star')

    # Add crosshair
    xlim = ax1.get_xlim()
    cursor = Cursor(ax1)
    plt.connect('motion_notify_event', cursor.mouse_move)
    ax1.set_xlim(xlim)

    if lines:
        y0, y1 = ax1.get_ylim()
        if rv1:
            shift = (1.0 + rv1 / 299792.458)
            for line in lines:
                ax1.vlines(line*shift, y0, y1, linewidth=2, color='m', alpha=0.5)
                ax1.text(line*shift-0.7, 1.2, str(line), rotation=90)
        else:
            for line in lines:
                ax1.vlines(line, y0, y1, linewidth=2, color='m', alpha=0.5)
                ax1.text(line-0.7, 1.2, str(line), rotation=90)

    ax1.set_xlabel('Wavelength')
    ax1.set_ylabel('"Normalized" flux')

    if len(rvs) == 1:
        if 'sun' in rvs.keys():
            ax2.plot(r_sun, c_sun, '-k', lw=2)
            ax2.plot(x_sun, y_sun, '--r', lw=2)
            ax2.set_title('CCF (sun)')
        if 'model' in rvs.keys():
            ax2.plot(r_mod, c_mod, '-k', lw=2)
            ax2.plot(x_mod, y_mod, '--r', lw=2)
            ax2.set_title('CCF (mod)')
        if 'telluric' in rvs.keys():
            ax2.plot(r_tel, c_tel, '-k', lw=2)
            ax2.plot(x_tel, y_tel, '--r', lw=2)
            ax2.set_title('CCF (tel)')
        ax2.set_xlabel('RV [km/s]')

    elif len(rvs) == 2:
        if 'sun' in rvs.keys():
            ax2.plot(r_sun, c_sun, '-k', lw=2)
            ax2.plot(x_sun, y_sun, '--r', lw=2)
            ax2.set_title('CCF (sun)')
        if 'model' in rvs.keys():
            ax2.plot(r_mod, c_mod, '-k', lw=2)
            ax2.plot(x_mod, y_mod, '--r', lw=2)
            ax2.set_title('CCF (mod)')
        ax3.plot(r_tel, c_tel, '-k', lw=2)
        ax3.plot(x_tel, y_tel, '--r', lw=2)
        ax3.set_title('CCF (tel)')

        ax2.set_xlabel('RV [km/s]')
        ax3.set_xlabel('RV [km/s]')

    if rv:
        ax1.set_title('%s\nRV correction: %s km/s' % (fname, rv))
    elif rv1 and rv2:
        ax1.set_title('%s\nSun/model: %s km/s, telluric: %s km/s' % (fname, rv1, rv2))
    elif rv1 and not rv2:
        ax1.set_title('%s\nSun/model: %s km/s' % (fname, rv1))
    elif not rv1 and rv2:
        ax1.set_title('%s\nTelluric: %s km/s' % (fname, rv2))
    elif ccf == 'model':
        ax1.set_title('%s\nModel(CCF): %s km/s' % (fname, rv1))
    elif ccf == 'sun':
        ax1.set_title('%s\nSun(CCF): %s km/s' % (fname, rv1))
    elif ccf == 'telluric':
        ax1.set_title('%s\nTelluric(CCF): %s km/s' % (fname, rv2))
    elif ccf == 'both':
        ax1.set_title('%s\nSun/model(CCF): %s km/s, telluric(CCF): %s km/s' % (fname, rv1, rv2))
    else:
        ax1.set_title(fname)
    if sun or telluric or model:
        ax1.legend(loc=3, frameon=False)
    plt.show()

    return rvs


if __name__ == '__main__':
    args = vars(_parser())
    fname = args.pop('fname')
    opts = {k: args[k] for k in args}

    main(fname, **opts)
