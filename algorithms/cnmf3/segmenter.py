#!/usr/bin/env python
# coding: utf-8
"""
This script identifies the boundaries of a given track using a novel C-NMF
method (v3).
"""

__author__ = "Oriol Nieto"
__copyright__ = "Copyright 2014, Music and Audio Research Lab (MARL)"
__license__ = "GPL"
__version__ = "1.0"
__email__ = "oriol@nyu.edu"

import argparse
import logging
import numpy as np
import time
from scipy.spatial import distance
from scipy.ndimage import filters
import sys
import pylab as plt
from scipy.cluster.vq import whiten, vq, kmeans

sys.path.append("../../")
import msaf_io as MSAF
import utils as U
try:
    import pymf
except:
    logging.error("PyMF module not found, C-NMF won't work")
    sys.exit()


def median_filter(X, M=8):
    """Median filter along the first axis of the feature matrix X."""
    for i in xrange(X.shape[1]):
        X[:, i] = filters.median_filter(X[:, i], size=M)
    return X


def cnmf(S, rank, niter=500, hull=False):
    """(Convex) Non-Negative Matrix Factorization.

    Parameters
    ----------
    S: np.array(p, N)
        Features matrix. p row features and N column observations.
    rank: int
        Rank of decomposition
    niter: int
        Number of iterations to be used

    Returns
    -------
    F: np.array
        Cluster matrix (decomposed matrix)
    G: np.array
        Activation matrix (decomposed matrix)
        (s.t. S ~= F * G)
    """
    if hull:
        nmf_mdl = pymf.CHNMF(S, num_bases=rank)
    else:
        nmf_mdl = pymf.CNMF(S, num_bases=rank)
    nmf_mdl.factorize(niter=niter)
    F = np.asarray(nmf_mdl.W)
    G = np.asarray(nmf_mdl.H)
    return F, G


def most_frequent(x):
    """Returns the most frequent value in x."""
    return np.argmax(np.bincount(x))


def compute_labels(X, rank, bound_idxs, dist="correlation", k=5):
    D = distance.pdist(X.T, metric=dist)
    D = distance.squareform(D)
    D /= D.max()
    S = 1 - D

    F, G = cnmf(S, rank)

    D = np.zeros((S.shape[0], rank))
    for r in xrange(rank):
        R = np.dot(F[:, r, np.newaxis], G[np.newaxis, r, :])
        #plt.imshow(R, interpolation="nearest"); plt.show()
        D[:, r] = np.diag(R)

    Dw = whiten(D)
    codebook, dist = kmeans(Dw, k)
    label_frames, disto = vq(Dw, codebook)
    #print label_frames, bound_idxs

    # Collapse labels based on the boundaries
    labels = [label_frames[0]]
    bound_inters = zip(bound_idxs[:-1], bound_idxs[1:])
    #bound_inters = [(0, bound_idxs[0])] + bound_inters
    for bound_inter in bound_inters:
        if bound_inter[1] - bound_inter[0] <= 0:
            labels.append(k)
        else:
            labels.append(most_frequent(
                label_frames[bound_inter[0]: bound_inter[1]]))
    labels.append(label_frames[-1])

    #plt.imshow(Dw, interpolation="nearest", aspect="auto"); plt.show()

    return labels


def compute_labels2(X, rank, R, bound_idxs, niter=300):
    """Computes the labels using the bounds."""

    try:
        F, G = cnmf(X, rank, niter=niter, hull=False)
    except:
        return [1]

    label_frames = filter_activation_matrix(G.T, R)
    label_frames = np.asarray(label_frames, dtype=int)

    labels = [label_frames[0]]
    bound_inters = zip(bound_idxs[:-1], bound_idxs[1:])
    for bound_inter in bound_inters:
        if bound_inter[1] - bound_inter[0] <= 0:
            labels.append(np.max(label_frames) + 1)
        else:
            labels.append(most_frequent(
                label_frames[bound_inter[0]: bound_inter[1]]))
        #print bound_inter, labels[-1]
    labels.append(label_frames[-1])

    return labels


def filter_activation_matrix(G, R):
    """Filters the activation matrix G, and returns a flattened copy."""

    #originalG = np.copy(G)
    idx = np.argmax(G, axis=1)
    max_idx = np.arange(G.shape[0])
    max_idx = (max_idx, idx.flatten())
    G[:, :] = 0
    G[max_idx] = idx + 1

    # TODO: Order matters?
    #oG = np.copy(G)
    G = np.sum(G, axis=1)
    G = median_filter(G[:, np.newaxis], R)
    #plt.subplot(1, 2, 1)
    #plt.imshow(originalG, interpolation="nearest", aspect="auto")
    #plt.subplot(1, 2, 2)
    #plt.imshow(F, interpolation="nearest", aspect="auto"); plt.show()

    return G.flatten()


def get_segmentation(X, rank, R, niter=300, bound_idxs=None):
    """
    Gets the segmentation (boundaries and labels) from the factorization
    matrices.

    Parameters
    ----------
    X: np.array()
        Features matrix (e.g. chromagram)
    rank: int
        Rank of decomposition
    R: int
        Size of the median filter for activation matrix
    niter: int
        Number of iterations for k-means
    bound_idxs : list
        Use previously found boundaries (None to detect them)

    Returns
    -------
    bounds_idx: np.array
        Bound indeces found
    labels: np.array
        Indeces of the labels representing the similarity between segments.
    """

    # Find non filtered boundaries
    while True:
        if bound_idxs is None:
            try:
                F, G = cnmf(X, rank, niter=niter, hull=False)
            except:
                return np.empty(0), [1]

            # Filter G
            G = filter_activation_matrix(G.T, R)
            if bound_idxs is None:
                bound_idxs = np.where(np.diff(G) != 0)[0] + 1

        # Obtain labels
        #labels = np.concatenate(([G[0]], G[bound_idxs]))

        #labels = compute_labels(X, 5, bound_idxs, k=4)
        #print len(bound_idxs), len(labels)

        # Increase rank if we found too few boundaries
        if len(np.unique(bound_idxs)) <= 2:
            rank += 1
            bound_idxs = None
        else:
            break

    rank_labels = 5
    R_labels = 6
    bound_idxs = np.asarray(bound_idxs, dtype=int)
    labels = compute_labels2(X, rank_labels, R_labels, bound_idxs)

    #plt.imshow(G.T, interpolation="nearest", aspect="auto")
    #for b in bound_idxs:
        #plt.axvline(b, linewidth=2.0, color="k")
    #plt.show()

    return bound_idxs, labels


def process(in_path, feature="hpcp", annot_beats=False, annot_bounds=False,
            h=10, R=9, rank=3):
    """Main process.

    Parameters
    ----------
    in_path : str
        Path to audio file
    feature : str
        Identifier of the features to use
    annot_beats : boolean
        Whether to use annotated beats or not
    annot_bounds : boolean
        Whether to use annotated bounds or not (for labeling)
    h : int
        Size of median filter
    R : int
        Size of the median filter for activation matrix
    rank : int
        Rank of decomposition

    """

    # C-NMF params
    niter = 300     # Iterations for the matrix factorization and clustering

    # Read features
    chroma, mfcc, beats, dur = MSAF.get_features(in_path,
                                                 annot_beats=annot_beats)

    # Read annotated bounds if necessary
    bound_idxs = None
    if annot_bounds:
        try:
            bound_idxs = MSAF.read_annot_bound_frames(in_path, beats)[1:-1]
        except:
            logging.warning("No annotated boundaries in file %s" % in_path)

    # Use specific feature
    if feature == "hpcp":
        F = U.lognormalize_chroma(chroma)  # Normalize chromas
    elif "mfcc":
        F = mfcc
    elif "tonnetz":
        F = U.lognormalize_chroma(chroma)  # Normalize chromas
        F = U.chroma_to_tonnetz(F)
    else:
        logging.error("Feature type not recognized: %s" % feature)

    if F.shape[0] >= h:
        # Median filter
        F = median_filter(F, M=h)
        #plt.imshow(F.T, interpolation="nearest", aspect="auto"); plt.show()

        # Find the boundary indices and labels using matrix factorization
        bound_idxs, est_labels = get_segmentation(
            F.T, rank, R, niter=niter, bound_idxs=bound_idxs)
    else:
        # The track is too short. We will only output the first and last
        # time stamps
        bound_idxs = np.empty(0)
        est_labels = [1]

    # Add first and last boundary
    bound_idxs = np.concatenate(([0], bound_idxs)).astype(int)
    est_times = beats[bound_idxs]  # Index to times
    est_times = np.concatenate((est_times, [dur]))  # Last bound

    #logging.info("Annotated bounds: %s" % ann_bounds)
    #logging.info("Estimated bounds: %s" % bound_idxs)

    logging.info("Estimated times: %s" % est_times)
    logging.info("Estimated labels: %s" % est_labels)

    assert len(est_times) - 1 == len(est_labels)

    return est_times, est_labels


def main():
    """Main function to parse the arguments and call the main process."""
    parser = argparse.ArgumentParser(description=
        "Segments the given audio file using the new version of the C-NMF "
                                     "method.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("in_path",
                        action="store",
                        help="Input path to the audio file")
    parser.add_argument("-f",
                        action="store",
                        dest="feature",
                        help="Feature to use (mfcc or hpcp)",
                        default="hpcp")
    parser.add_argument("-b",
                        action="store_true",
                        dest="annot_beats",
                        help="Use annotated beats",
                        default=False)
    parser.add_argument("-bo",
                        action="store_true",
                        dest="annot_bounds",
                        help="Use annotated bounds",
                        default=False)
    args = parser.parse_args()
    start_time = time.time()

    # Setup the logger
    logging.basicConfig(format='%(asctime)s: %(levelname)s: %(message)s',
        level=logging.INFO)

    # Run the algorithm
    process(args.in_path, feature=args.feature, annot_beats=args.annot_beats,
            annot_bounds=args.annot_bounds)

    # Done!
    logging.info("Done! Took %.2f seconds." % (time.time() - start_time))

if __name__ == '__main__':
    main()