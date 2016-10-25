import sys
import os
from dataset_loaders.parallel_loader import ThreadedDataset
from matplotlib.path import Path
from PIL import Image
import warnings
import dataset_loaders
import numpy as np


floatX = 'float32'


class CocoDataset(ThreadedDataset):
    name = 'mscoco'
    nclasses = 80
    debug_shape = (3, 255, 255)

    # optional arguments
    # GT_classes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18,
    #               19, 20, 21, 22, 23, 24, 25, 27, 28, 31, 32, 33, 34, 35, 36,
    #               37, 38, 39, 40, 41, 42, 43, 44, 46, 47, 48, 49, 50, 51, 52,
    #               53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 67, 70,
    #               72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84, 85, 86, 87,
    #               88, 89, 90]
    _void_labels = [0, 12, 26, 29, 30, 45, 66, 68, 69, 71, 83]

    _filenames = None

    @property
    def filenames(self):
        if self._filenames is None:
            self._filenames = self.coco.loadImgs(self.img_ids)
        return self._filenames

    def __init__(self, which_set='train', warn_grayscale=False,
                 val_test_split=0.5, *args, **kwargs):
        sys.path.append(os.path.join(os.path.dirname(
            os.path.abspath(__file__)), 'coco', 'PythonAPI'))
        from pycocotools.coco import COCO
        self.which_set = 'val' if which_set == 'valid' else which_set
        self.warn_grayscale = warn_grayscale
        self.path = os.path.join(dataset_loaders.__path__[0], 'datasets',
                                 'COCO')
        self.sharedpath = '/data/lisa/data/COCO'

        if self.which_set == 'train':
            self.image_path = os.path.join(self.path, 'images', 'train2014')
            self.coco = COCO(os.path.join(self.path, 'annotations',
                                          'instances_train2014.json'))
        elif self.which_set == 'val':
            self.image_path = os.path.join(self.path, 'images', 'val2014')
            self.coco = COCO(os.path.join(self.path, 'annotations',
                                          'instances_val2014.json'))
        elif self.which_set == 'test':
            self.image_path = os.path.join(self.path, 'images', 'test2015')
            self.coco = COCO(os.path.join(self.path, 'annotations',
                                          'image_info_test2015.json'))
            self.has_GT = False
        self.img_ids = self.coco.getImgIds()
        self.catIds = self.coco.getCatIds()

        # constructing the ThreadedDataset
        # it also creates/copies the dataset in self.path if not already there
        super(CocoDataset, self).__init__(*args, **kwargs)

    def get_names(self):
        seq_length = self.seq_length
        seq_per_video = self.seq_per_video
        if seq_length != 1 or seq_per_video != 0:
            raise NotImplementedError('Images in COCO are not sequential. '
                                      'It does not make sense to request a '
                                      'sequence. seq_length {} '
                                      'seq_per_video {}'.format(seq_length,
                                                                seq_per_video))
        filenames = self.filenames
        # Allow to use negative overlap to select a subset of the
        # dataset
        overlap = self.overlap if self.overlap < 0 else 1
        return np.array(filenames[::-overlap])

    def load_sequence(self, img):
        from pycocotools import mask as cocomask
        if not os.path.exists('%s/%s' % (self.image_path, img['file_name'])):
            raise RuntimeError('Image %s is missing' % img['file_name'])

        im = Image.open('%s/%s' % (self.image_path, img['file_name'])).copy()
        if im.mode == 'L':
            if self.warn_grayscale:
                warnings.warn('image %s is grayscale..' % img['file_name'],
                              RuntimeWarning)
            im = im.convert('RGB')

        # load the annotations and build the mask
        anns = self.coco.loadAnns(self.coco.getAnnIds(
                imgIds=img['id'], catIds=self.catIds, iscrowd=None))

        mask = np.zeros(im.size).transpose(1, 0)
        for ann in anns:
            catId = ann['category_id']
            if type(ann['segmentation']) == list:
                # polygon
                for seg in ann['segmentation']:
                    # xy vertex of the polygon
                    poly = np.array(seg).reshape((len(seg)/2, 2))
                    closed_path = Path(poly)
                    nx, ny = img['width'], img['height']
                    x, y = np.meshgrid(np.arange(nx), np.arange(ny))
                    x, y = x.flatten(), y.flatten()
                    points = np.vstack((x, y)).T
                    grid = closed_path.contains_points(points)
                    if np.count_nonzero(grid) == 0:
                        warnings.warn(
                            'One of the annotations that compose the mask '
                            'of %s was empty' % img['file_name'],
                            RuntimeWarning)
                    grid = grid.reshape((ny, nx))
                    mask[grid] = catId
            else:
                # mask
                if type(ann['segmentation']['counts']) == list:
                    rle = cocomask.frPyObjects(
                        [ann['segmentation']],
                        img['height'], img['width'])
                else:
                    rle = [ann['segmentation']]
                grid = cocomask.decode(rle)[:, :, 0]
                grid = grid.astype('bool')
                mask[grid] = catId

        mask = np.array(mask.astype('int32'))
        im = np.array(im).astype(floatX)/255.
        im, mask = im[None, ...], mask[None, ...]  # add dim

        ret = {}
        ret['data'] = im
        ret['labels'] = mask
        ret['filenames'] = img['file_name']
        return ret
