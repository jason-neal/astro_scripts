#!/usr/bin/env python
# -*- coding: utf8 -*-

# My imports
from __future__ import division, print_function
import numpy as np
import scipy.interpolate as sci
import matplotlib.pyplot as plt
import matplotlib
from astropy.io import fits
import argparse

path = '/home/daniel/Documents/Uni/phdproject/programs/astro_scripts/'
pathsun = path + 'solarspectrum_01.fits'
pathtel = path + 'telluric_NIR.fits'


def ccf(spectrum1, spectrum2, rvmin=0, rvmax=200, drv=1):
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
    c = 299792.458
    drvs = np.arange(rvmin, rvmax, drv)
    cc = np.zeros(len(drvs))
    for i, rv in enumerate(drvs):
        fi = sci.interp1d(tw * (1.0 + rv/c), tf)
        # Shifted template evaluated at location of spectrum
        try:
            fiw = fi(w)
        except ValueError:
            s = True
            pass
        cc[i] = np.sum(f * fiw)

    if s:
        print('Warning: You should lower the bounds on RV')
    # Fit the CCF with a gaussian
    ampl = max(cc)
    mean = cc[cc == ampl]
    I = np.where(cc == ampl)[0]
    g_init = models.Gaussian1D(amplitude=ampl, mean=mean, stddev=1)
    fit_g = fitting.LevMarLSQFitter()
    g = fit_g(g_init, drvs[I-30:I+30], cc[I-30:I+30])

    RV = drvs[g(cc) == max(g(cc))][0]
    return RV, drvs, cc


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

    wl2inv = (1.e4/wl)**2
    refracstp = 272.643 + 1.2288 * wl2inv + 3.555e-2 * wl2inv**2
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
    wlprime = wvl * (1.0 + v/299792.458)
    i = np.argmin(abs(wvl - 12780.6))

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


def _parser():
    """Take care of all the argparse stuff.

    :returns: the args
    """
    parser = argparse.ArgumentParser(description='Plot fits file for ARES. Be'
                                     ' careful with large files')
    parser.add_argument('input', help='Input fits file')
    parser.add_argument('-s', '--sun', help='Plot with spectra of the Sun ',
                        action='store_true')
    parser.add_argument('-t', '--telluric', help='Plot telluric with spectrum',
                        action='store_true')
    parser.add_argument('-r', '--rv', help='RV correction to the spectra in'
                        'km/s', default=False, type=float)
    parser.add_argument('-r1', '--rv1', help='RV correction to the spectra in'
                        'km/s (model/Sun)', default=False, type=float)
    parser.add_argument('-r2', '--rv2', help='RV correction to the spectra in'
                        'km/s (telluric)', default=False, type=float)
    parser.add_argument('-l', '--lines',
                        help='Lines to plot on top (multiple lines is an'
                        ' option). If multiple lines needs to be plotted, then'
                        ' separate with a space',
                        default=False, nargs='+', type=float)
    parser.add_argument('-m', '--model',
                        help='If not the Sun shoul be used as a model, put'
                        ' the model here (only support BT-Settl for the'
                        ' moment)',
                        default=False)
    parser.add_argument('-c', '--ccf', default='0',
                        choices=['s', 'm', 't', '2'],
                        help='Calculate the CCF for Sun/model or tellurics '
                             'or both.')
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    args = _parser()
    # print(args)

    fname = args.input
    I = fits.getdata(fname)
    I /= np.median(I)
    # Normalization (use first 50 points below 1.2 as continuum)
    maxes = I[(I < 1.2)].argsort()[-50:][::-1]
    I /= np.median(I[maxes])
    hdr = fits.getheader(fname)
    dw = 10  # Some extra coverage for RV shifts

    if args.rv:
        rv = args.rv
        w = get_wavelength(hdr)
        I, w = dopplerShift(wvl=w, flux=I, v=rv, fill_value=0.95)
    else:
        w = get_wavelength(hdr)
    w0, w1 = w[0] - dw, w[-1] + dw

    if args.sun and not args.model:
        I_sun = fits.getdata(pathsun)
        hdr = fits.getheader(pathsun)
        w_sun = get_wavelength(hdr)
        i = (w_sun > w0) & (w_sun < w1)
        w_sun = w_sun[i]
        I_sun = I_sun[i]
        I_sun /= np.median(I_sun)
        if args.ccf in 's2' and args.rv1:
            print('Warning: RV set for Sun. Calculate RV with CCF')
        if args.rv1 and args.ccf not in 's2':
            I_sun, w_sun = dopplerShift(wvl=w_sun, flux=I_sun, v=args.rv1,
                                        fill_value=0.95)

    if args.model:
        I_mod = fits.getdata(args.model)
        hdr = fits.getheader(args.model)
        w_mod = get_wavelength(hdr)
        nre = nrefrac(w_mod)  # Correction for vacuum to air (ground based)
        w_mod = w_mod / (1 + 1e-6 * nre)
        i = (w_mod > w0) & (w_mod < w1)
        w_mod = w_mod[i]
        I_mod = I_mod[i]
        I_mod = 10 ** (I_mod - 8.0)  # https://phoenix.ens-lyon.fr/Grids/FORMAT
        I_mod /= np.median(I_mod)
        # Normalization (use first 50 points below 1.2 as continuum)
        maxes = I_mod[(I_mod < 1.2)].argsort()[-50:][::-1]
        I_mod /= np.median(I_mod[maxes])
        if args.ccf in 'm2' and args.rv1:
            print('Warning: RV set for model. Calculate RV with CCF')
        if args.rv1 and args.ccf not in 'm2':
            I_mod, w_mod = dopplerShift(wvl=w_mod, flux=I_mod, v=args.rv1,
                                        fill_value=0.95)

    if args.telluric:
        I_tel = fits.getdata(pathtel)
        hdr = fits.getheader(pathtel)
        w_tel = get_wavelength(hdr)
        i = (w_tel > w0) & (w_tel < w1)
        w_tel = w_tel[i]
        I_tel = I_tel[i]
        I_tel /= np.median(I_tel)
        if args.ccf in 't2' and args.rv2:
            print('Warning: RV set for telluric, Calculate RV with CCF')
        if args.rv2 and args.ccf not in 't2':
            I_tel, w_tel = dopplerShift(wvl=w_tel, flux=I_tel, v=args.rv2,
                                        fill_value=0.95)

    if args.ccf != '0':
        from astropy.modeling import models, fitting

        if args.telluric and args.sun:
            I_sun = I_sun / I_tel  # remove tellurics from the Solar spectrum

        if args.ccf in 's2' and args.sun:
            rv1, r_sun, c_sun = ccf((w, -I+1), (w_sun, -I_sun+1))
            I_sun, w_sun = dopplerShift(w_sun, I_sun, v=rv1, fill_value=0.95)

        if args.ccf in 'm2' and args.model:
            rv1, r_mod, c_mod = ccf((w, -I+1), (w_mod, -I_mod+1))
            I_mod, w_mod = dopplerShift(w_mod, I_mod, v=rv1, fill_value=0.95)

        if args.ccf in 't2' and args.telluric:
            rv2, r_tel, c_mod = ccf((w, -I+1), (w_tel, -I_tel+1))
            I_tel, w_tel = dopplerShift(w_tel, I_tel, v=rv2, fill_value=0.95)

    fig = plt.figure(figsize=(16, 5))
    # Start in pan mode with these two lines
    manager = plt.get_current_fig_manager()
    manager.toolbar.pan()

    ax = fig.add_subplot(111)
    # Use nice numbers on x axis (y axis is normalized)...
    x_formatter = matplotlib.ticker.ScalarFormatter(useOffset=False)
    ax.xaxis.set_major_formatter(x_formatter)

    if args.sun and not args.model:
        ax.plot(w_sun, I_sun, '-g', lw=2, alpha=0.6, label='Sun')
    if args.telluric:
        ax.plot(w_tel, I_tel, '-r', lw=2, alpha=0.5, label='Telluric')
    if args.model:
        ax.plot(w_mod, I_mod, '-g', lw=2, alpha=0.5, label='Model')
    ax.plot(w, I, '-k', lw=2, label='Star')
    if args.lines:
        lines = args.lines
        y0, y1 = ax.get_ylim()
        ax.vlines(lines, y0, y1, linewidth=2, color='m', alpha=0.5)
    ax.set_xlabel('Wavelength')
    ax.set_ylabel('"Normalized" intensity')

    if args.rv:
        ax.set_title('%s\nRV correction: %s km/s' % (fname, args.rv))
    elif args.rv1 and args.rv2:
        ax.set_title('%s\nSun/model: %s km/s, telluric: %s km/s' % (fname,
                     args.rv1, args.rv2))
    elif args.rv1 and not args.rv2:
        ax.set_title('%s\nSun/model: %s km/s' % (fname, args.rv1))
    elif not args.rv1 and args.rv2:
        ax.set_title('%s\nTelluric: %s km/s' % (fname, args.rv2))
    elif args.ccf == 'm':
        ax.set_title('%s\nModel(CCF): %s km/s' % (fname, rv1))
    elif args.ccf == 's':
        ax.set_title('%s\nSun(CCF): %s km/s' % (fname, rv1))
    elif args.ccf == 't':
        ax.set_title('%s\nTelluric(CCF): %s km/s' % (fname, rv2))
    elif args.ccf == '2':
        ax.set_title('%s\nSun/model(CCF): %s km/s, telluric(CCF): %s km/s' %
                     (fname, rv1, rv2))
    else:
        ax.set_title(fname)
    if args.sun or args.telluric or args.model:
        ax.legend(loc=3, frameon=False)
    plt.show()