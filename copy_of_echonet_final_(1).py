# -*- coding: utf-8 -*-
"""Copy of EchoNet_Final (1).ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1KbDUlNGEIdADeN0qnqRGzNGBjw_w-Caj
"""

import os
import glob
import keras
import keras.applications
import pandas as pd
import numpy as np
import imageio
import cv2
import tensorflow as tf
from tqdm import tqdm
import keras.backend as K
from sklearn.metrics import mean_absolute_error
import matplotlib.pyplot as plt

image_size = (299,299,3)
max_sequence_length = 64
batch_size = 8
num_features = 2048
epochs = 6
learning_rate = 1e-4
path = r""
decay = 2

metadata = pd.read_csv(os.path.join(path,"FileList.csv"))
metadata.drop(axis=0,index=np.arange(10025,10030),inplace=True)

mask = metadata["NumberOfFrames"] <= 275
masked_data = metadata[mask]

vols = pd.read_csv("VolumeTracings.csv")

def load_avi(path, max_frames=0):
    capture = cv2.VideoCapture("Videos/" + path + ".avi")
    frames = []
    try:
        while True:
            ret, frame = capture.read()
            if not ret:
                break
            frame = frame[:,:,[2,1,0]]
            frames.append(frame)

            if len(frames) == max_frames:
                break
    finally:
        capture.release()
    for i in range(len(frames)):
        frame = frames[i]
        frames[i] = cv2.resize(frame,dsize=image_size[:2],interpolation=cv2.INTER_CUBIC)
    return np.array(frames) / 255.

def yield_video(filename,step=2):
    frame = vols.loc[(vols["FileName"] == filename + ".avi"),:]
    mask = frame["Frame"] == frame["Frame"].iloc[0]
    first = frame[mask]
    num1 = first["Frame"].iloc[0]
    second = frame[~mask]
    num2 = second["Frame"].iloc[0]
    video = load_avi(filename)
    samp_size = abs(num2-num1)
    if samp_size > max_sequence_length//2:
        video_sub = video[::step,:,:,:]
        large_key = int(num2//2)
        small_key = int(num1//2)
    else:
        large_key = num2
        small_key = num1
    f, h, w, c = video.shape
    first_poi = min(small_key, large_key)
    last_poi  = max(small_key, large_key)
    nvideo = []
    while len(nvideo) < max_sequence_length+1:
        nvideo.append(video[first_poi])
        nvideo.extend(video[first_poi+1:last_poi])
        nvideo.append(video[last_poi])
        nvideo.extend(video[last_poi-1:first_poi:-1])
    nvideo = np.stack(nvideo)
    start_index = np.random.randint(nvideo.shape[0]-max_sequence_length)
    nvideo = nvideo[start_index:start_index+max_sequence_length]
    return nvideo

def build_feature_extractor():
    feature_extractor = tf.keras.applications.xception.Xception(weights="imagenet",include_top=False,pooling="avg",input_shape=image_size)
    preprocess_input = keras.applications.xception.preprocess_input
    inputs = keras.Input(image_size)
    preprocessed = preprocess_input(inputs)
    outputs = feature_extractor(preprocessed)
    return keras.Model(inputs,outputs,name="extractor")

feature_extractor = build_feature_extractor()

def prepare_data(df,root_dir):
    num_samples = len(df)
    video_paths = df["FileName"].values.tolist()
    ef = df["EF"].values
    frame_features = np.zeros(shape=(num_samples,max_sequence_length,num_features),dtype="float32")
    for idx,video_path in enumerate(video_paths):
        frames = yield_video(video_path,step=2)
        frames = frames[None,...]
        temp_frame_features = np.zeros(shape=(1,max_sequence_length,num_features),dtype="float32")
        for i,batch in enumerate(frames):
            video_length = batch.shape[0]
            temp_frame_features[i,:,:] = feature_extractor.predict(batch[:,:],verbose=0)
        frame_features[idx,] = temp_frame_features.squeeze()
    return frame_features,ef

class PrepareVideosGen(tf.keras.utils.Sequence):
    def __init__(self,df,batch_size):
        self.df = df.copy()
        self.batch_size = batch_size
        self.input_size = image_size
        self.n = len(self.df)

    def on_epoch_end(self):
        pass

    def __getitem__(self,index):
        batches = self.df[(index*self.batch_size):((index+1)*self.batch_size)]
        X,y = prepare_data(batches,path)
        return X,y

    def __len__(self):
        return self.n//self.batch_size

def build_encoder():
    inputs = keras.Input(shape=(max_sequence_length,num_features))
    x = keras.layers.Conv1D(128,padding='valid',kernel_size=7,activation='swish')(inputs)
    x = keras.layers.Conv1D(256,padding='valid',kernel_size=5,activation='swish')(x)
    x = keras.layers.GlobalMaxPooling1D()(x)
    x = keras.layers.Dense(256,activation="swish")(x)
    x = keras.layers.Dense(256,activation="swish")(x)
    outputs = keras.layers.Dense(1,activation="linear")(x)
    model = keras.Model(inputs,outputs)
    model.compile(loss=tf.keras.losses.MeanSquaredError(),optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate,epsilon=1e-8),metrics=[tf.keras.losses.MeanAbsoluteError()])
    return model

train_gen = PrepareVideosGen(masked_data.loc[masked_data["Split"] == "TRAIN",:],batch_size=batch_size)
val_gen = PrepareVideosGen(masked_data.loc[masked_data["Split"] == "VAL",:],batch_size=batch_size)
checkpoint = keras.callbacks.ModelCheckpoint(filepath="models/conv1d.{epoch:02d}-{val_loss:.2f}.hdf5",save_weights_only=True,save_best_only=False)
encoder_model = build_encoder()
history = encoder_model.fit(train_gen,epochs=20,callbacks=[checkpoint],validation_data=val_gen)