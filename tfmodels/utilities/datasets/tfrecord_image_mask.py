from __future__ import print_function

import tensorflow as tf
"""
TODO:
https://www.tensorflow.org/programmers_guide/datasets#applying_arbitrary_python_logic_with_tfpy_func

TODO:
We can have multiple initialized datasets sitting around and feed the initializer
into the placeholder via feed_dict:
REF: https://github.com/tensorflow/tensorflow/blob/master/tensorflow/docs_src/programmers_guide/datasets.md

^ Maybe drawback is all their queues would keep full and flood the memory.
^ Need to check behavior.

TFRecordDataset(training_record = None,
    testing_record = None,
    crop_size = 512,
    ratio = 1.0,
    batch_size = 32,
    prefetch = 1000,
    shuffle_buffer = 512,
    n_threads = 4,
    sess = None,
    as_onehot = True,
    n_classes = True,
    img_dtype = tf.uint8,
    mask_dtype = tf.uint8,
    img_channels = 3,
    preprocess = ['brightness', 'hue', 'saturation', 'contrast'],
    name = 'TFRecordDataset' )
"""

class TFRecordImageMask(object):
    def __init__(self, **kwargs):
        defaults = {'training_record': None,
                    'testing_record': None,
                    'crop_size': 512,
                    'ratio': 1.0,
                    'repeat': True,
                    'batch_size': 32,
                    'prefetch': 256,
                    'shuffle_buffer': 128,
                    'n_threads': 4,
                    'sess': None,
                    'as_onehot': True,
                    'target_image': False,
                    'n_classes': None,
                    'img_dtype': tf.uint8,
                    'mask_dtype': tf.uint8,
                    'img_channels': 3,
                    'mask_channels': 1,
                    'preprocess': ['brightness', 'hue', 'saturation', 'contrast'],
                    'name': 'TFRecordDataset' }
        defaults.update(kwargs) 

        for key,val in defaults.items():
            setattr(self, key, val)

        assert self.training_record is not None

        self.initialized = False

        self.record_path = tf.placeholder_with_default(self.training_record, shape=())
        self.dataset = self._make_dataset()
        # self.dataset = (tf.data.TFRecordDataset(self.record_path)
        #                 .repeat()
        #                 .shuffle(buffer_size=self.shuffle_buffer)
        #                 .map(lambda x: self._preprocessing(x, self.crop_size, self.ratio),
        #                     num_parallel_calls=self.n_threads)
        #                 .batch(self.batch_size) 
        #                 .prefetch(buffer_size=self.prefetch)
        #                 )

        self.iterator = self.dataset.make_initializable_iterator()
        self.image_op, self.mask_op = self.iterator.get_next()

        if self.sess is not None:
            self._initalize_training(self.sess)

    def _make_dataset(self):
        """ Construct the dataset functions one by one instead of assuming defaults

        TODO: add argument checking and error messages
        """
        dataset = tf.data.TFRecordDataset(self.record_path)
        if self.repeat:
            dataset = dataset.repeat()

        if self.shuffle_buffer:
            dataset = dataset.shuffle(buffer_size=self.shuffle_buffer)

        # We always have a crop and ratio .. ?
        # TODO check sanity for n_threads argument
        dataset = dataset.map(
            lambda x: self._preprocessing(x, self.crop_size, self.ratio), 
            num_parallel_calls=self.n_threads
        )
        
        if self.batch_size:
            dataset = dataset.batch(self.batch_size)

        if self.prefetch:
            dataset = dataset.prefetch(buffer_size=self.prefetch)

        return dataset

    def _initalize_training(self, sess):
        fd = {self.record_path: self.training_record}
        sess.run(self.iterator.initializer, feed_dict=fd)
        self.phase = 'TRAIN'
        print('Dataset TRAINING phase')

    def _initalize_testing(self, sess):
        if self.testing_record is None:
            print('WARNING DATSET {} HAS NO TEST RECORD'.format(self.name))
            return
        fd = {self.record_path: self.testing_record}
        sess.run(self.iterator.initializer, feed_dict=fd)
        self.phase = 'TEST'
        print('Dataset TESTING phase')

    def _decode(self, example):
        """ Decode an image / mask pair from tfrecord example
        
        """
        features = {'height': tf.FixedLenFeature((), tf.int64, default_value=0),
                    'width': tf.FixedLenFeature((), tf.int64, default_value=0),
                    'img': tf.FixedLenFeature((), tf.string, default_value=''),
                    'mask': tf.FixedLenFeature((), tf.string, default_value=''), }
        pf = tf.parse_single_example(example, features)

        height = tf.squeeze(pf['height'])
        width = tf.squeeze(pf['width'])

        img = pf['img']
        mask = pf['mask']
        img = tf.decode_raw(img, self.img_dtype)
        mask = tf.decode_raw(mask, self.mask_dtype)
        # img = tf.image.decode_image(img)
        # mask = tf.image.decode_image(mask)

        img = tf.cast(img, tf.float32)
        mask = tf.cast(mask, tf.float32)

        return height, width, img, mask

    def _preprocessing(self, example, crop_size, ratio):
        """ Construct the preprocessing steps

        """
        h, w, img, mask = self._decode(example)
        img_shape = tf.stack([h, w, self.img_channels], axis=0)
        mask_shape = tf.stack([h, w, self.mask_channels], axis=0)

        img = tf.reshape(img, img_shape)
        mask = tf.reshape(mask, mask_shape)

        if len(mask.shape) == 2:
            mask = tf.expand_dims(mask, axis=-1)
        image_mask = tf.concat([img, mask], axis=-1)

        image_mask = tf.random_crop(image_mask,
            [crop_size, crop_size, self.img_channels + self.mask_channels])
        image_mask = tf.image.random_flip_left_right(image_mask)
        image_mask = tf.image.random_flip_up_down(image_mask)
        img, mask = tf.split(image_mask, [self.img_channels, self.mask_channels], axis=-1)

        for px in self.preprocess:
            if px == 'brightness':
                img = tf.image.random_brightness(img, max_delta=0.1)

            elif px == 'contrast':
                img = tf.image.random_contrast(img, lower=0.4, upper=0.8)

            elif px == 'hue':
                img = tf.image.random_hue(img, max_delta=0.1)

            elif px == 'saturation':
                img = tf.image.random_saturation(img, lower=0.4, upper=0.8)

        target_h = tf.cast(crop_size*ratio, tf.int32)
        target_w = tf.cast(crop_size*ratio, tf.int32)
        img = tf.image.resize_images(img, [target_h, target_w])
        mask = tf.image.resize_images(mask, [target_h, target_w], method=1) ## nearest neighbor

        ## Recenter to [-1, 1] for SELU activations
        # img = tf.cast(img, tf.float32)
        img = tf.multiply(img, 2/255.0) - 1

        if self.as_onehot:
            mask = tf.cast(mask, tf.uint8)
            mask = tf.one_hot(mask, depth=self.n_classes)
            mask = tf.squeeze(mask)

        if self.target_image:
            mask = tf.multiply(mask, 2/255.0) - 1

        return img, mask

    def print_info(self):
        print('-------------------- {} ---------------------- '.format(self.name))
        for key, value in sorted(self.__dict__.items()):
            print('|\t{}: {}'.format(key, value))
        print('-------------------- {} ---------------------- '.format(self.name))
