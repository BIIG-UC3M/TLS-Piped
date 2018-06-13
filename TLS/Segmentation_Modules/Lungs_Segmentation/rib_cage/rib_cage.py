#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 23 10:46:33 2018

@author: pmacias
"""
import SimpleITK
import numpy as np
from scipy.spatial.distance import euclidean
from scipy.spatial import ConvexHull
from scipy.spatial import Voronoi

import glob

def multi_label_mask(itk_image, labels):
    img_out = SimpleITK.Image(itk_image.GetSize(), SimpleITK.sitkUInt8)
    img_out.CopyInformation(itk_image)
    for l in labels:
        img_out+= itk_image == l
    return img_out

def distance_objects(itk_image, image_center = None):
    image_center = itk_image.TransformIndexToPhysicalPoint( np.array(itk_image.GetSize())/2) if image_center is None else image_center
    shape_stats = SimpleITK.LabelShapeStatisticsImageFilter()
    shape_stats.Execute(itk_image)
    return np.array(shape_stats.GetLabels()),[euclidean(shape_stats.GetCentroid(label), image_center) for label in shape_stats.GetLabels() ]

def get_scapula_labels(bone_image, ref_slice = None, num_s = 2):
    if ref_slice is not None:
        ref_slice = ref_slice
        bone_image = bone_image[:,:,ref_slice]
    labels,distances = distance_objects(bone_image)

    return labels[np.argsort(distances)[-num_s:]].reshape(num_s,1) if len(distances) > 1 else labels.reshape(1,1)

def get_CT_bones_rude(itk_image, n_th = 3, bone_limit = [500,1200], size_limit = 1.0, ref_slice = -1):
    '''
    Basically separates the volume  hypothesizing trimodal histogram (bone/background/tissue) to obtain the bone (higher histogrmam)
    Next, get the connected bones, filtering outliers in intensity, distance and size to get and remove the scapulas
    '''
    
    otsu = SimpleITK.OtsuMultipleThresholds(itk_image, numberOfThresholds = n_th)
    intensity_stats = SimpleITK.LabelIntensityStatisticsImageFilter()
    intensity_stats.Execute(otsu, itk_image)

    labels_median = [intensity_stats.GetMedian(l) for l in intensity_stats.GetLabels() ]
    sorted_labels_indx = np.argsort(labels_median)
    print(sorted_labels_indx)
    bone_label = sorted_labels_indx[-1] + 1 #Max intensity is bone
    print('bone_labels',bone_label)
    
    lung_label = sorted_labels_indx[0] + 1 #After backgorund lowe intensity should be lungs. Always under the trimodal hypotesis
    print('Lung label' ,lung_label)

    bone_mask = otsu == bone_label
    bone_mask = SimpleITK.Median(bone_mask, [4,4,4])
    connected_bones = SimpleITK.ConnectedComponent(bone_mask)
    
    lung_mask = otsu == lung_label
    lung_mask = SimpleITK.Median(lung_mask, [4,4,4])
    connected_lung = SimpleITK.ConnectedComponent(lung_mask)
    #TODO. Now is Ad-hoc for simpel images. Should be probabilistic
    intensity_stats.Execute(connected_lung, itk_image)
    lungs_sizes = [intensity_stats.GetPhysicalSize(i) for i in intensity_stats.GetLabels()]
    lung_sizes_indx_sort = np.argsort(lungs_sizes)
    print('lung label', intensity_stats.GetLabels()[lung_sizes_indx_sort[-2]] )
    lung_mask = connected_lung == intensity_stats.GetLabels()[lung_sizes_indx_sort[-2]] 
    
    
    intensity_stats.Execute(connected_bones, itk_image)
    labels = np.array(intensity_stats.GetLabels())
    intensities = np.array([intensity_stats.GetMedian(l) for l in labels ])
    labels = labels [(intensities > bone_limit[0]) * (intensities < bone_limit[1])]
    sizes = np.array([intensity_stats.GetPhysicalSize(l) for l in labels])
    
    labels = labels[ sizes > size_limit  ]
    
    lowers = np.array([intensity_stats.GetCentroid(l)[1] for l in labels])
    lim_y = itk_image.TransformIndexToPhysicalPoint(itk_image.GetSize())[1]
    labels = labels[lowers < (lim_y - 9)]
    
    connected_bones = SimpleITK.Mask(connected_bones, multi_label_mask(connected_bones, labels))
    scp_labels = get_scapula_labels(connected_bones, ref_slice = ref_slice)
    print scp_labels, type(scp_labels)
    labels = labels[ np.prod(labels != scp_labels, axis = 0, dtype = np.bool) ]
    no_scp_bones = multi_label_mask(connected_bones, labels)
    return otsu, bone_mask, SimpleITK.Mask(itk_image, bone_mask), connected_bones,SimpleITK.Mask(connected_bones, no_scp_bones), SimpleITK.Mask(itk_image, no_scp_bones), no_scp_bones, lung_mask, connected_lung


class MASK_DOWNSAMPLING():
    CONTOUR = SimpleITK.BinaryContourImageFilter()
    THINNING = SimpleITK.BinaryThinningImageFilter()

def get_rib_cage_convex_hull(rib_cage_mask, downsamplig = MASK_DOWNSAMPLING.THINNING):
    rib_cage_mask = downsamplig.Execute(rib_cage_mask) if downsamplig is not None else rib_cage_mask
    mask_array = SimpleITK.GetArrayFromImage(rib_cage_mask)
    points = np.stack([indx for indx in np.where(mask_array)], axis = 1)
    return points,Voronoi(points) #ConvexHull(points)

def get_bounding_box(original_image, rib_cage_mask, lung_mask,  include_bones = True):
    if original_image.GetSize() != rib_cage_mask.GetSize():
        print('Dimensions must be equal:',original_image.GetSize(), rib_cage_mask.GetSize())
    h,w,d = original_image.GetSize()
    rib_cage_mask = rib_cage_mask > 0 #Just in case
    box_filter = SimpleITK.LabelShapeStatisticsImageFilter()
    box_filter.Execute(rib_cage_mask)
    x_rc_1,y_rc_1,z_rc_1,dx_rc,dy_rc,dz_rc = box_filter.GetBoundingBox(1)
    x_rc_2 = x_rc_1 + dx_rc; y_rc_2 = y_rc_1 + dy_rc; z_rc_2 = z_rc_1 + dz_rc #Rib cage points bounding box
    
    box_filter.Execute(lung_mask)
    x_lm_1,y_lm_1,z_lm_1,dx_lm,dy_lm,dz_lm = box_filter.GetBoundingBox(1)
    x_lm_2 = x_lm_1 + dx_lm; y_lm_2 = y_lm_1 + dy_lm; z_lm_2 = z_lm_1 + dz_lm
    
    #union_box_x = TODO
    print('ribcg points',x_rc_1,y_rc_1,z_rc_1,x_rc_2,y_rc_2,z_rc_2)
    print('lungs points',x_lm_1,y_lm_1,z_lm_1,x_lm_2,y_lm_2,z_lm_2 )
    x1 = min(x_rc_1, x_lm_1)
    y1 = min(y_rc_1, y_lm_1)
    z1 = min(z_rc_1, z_lm_1)
    x2 = max(x_rc_2, x_lm_2)
    y2 = max(y_rc_2, y_lm_2)
    z2 = max(z_rc_2, z_lm_2)
    print(x1,y1,z1,x2,y2,z2)
    
    
    original_image = SimpleITK.Mask(original_image, rib_cage_mask < 1) if include_bones is False else original_image
    print([h - x2, w - y2, d - z2 ])
    return SimpleITK.Crop(original_image, [x1,y1,z1], [h - x2, w - y2, d - z2 ])
  

if __name__ == "__main__":
    image_path = ('/media/pmacias/DATA2/amunoz/LOTE_2-study_5007/Study-5007/049JID/2.3WEEKS_26JUL14/5007_049JID_3WEEKSW_Segmentation/5007_049JID_3WEEKSW_Segmentation_oneFileVolume.mhd')
    
    images = glob.glob('/media/pmacias/DATA2/amunozs/LOTE_2-study_5007/Study-5007/*/*/*/*oneFileVolume.mhd')
    
    for image in images:
        fields = image.split('/')[-2].split('_')
        s = fields[1]
        w = fields[2].split('W')[0]
        image = SimpleITK.ReadImage(image)
        name = s+'_'+w+'.mhd'
        print (name)
        a = get_CT_bones_rude(image, n_th=3)
        #SimpleITK.WriteImage(a[0],'/tmp/otsu.mhd')
        #SimpleITK.WriteImage(a[1],'/tmp/bone_mask.mhd')
        #SimpleITK.WriteImage(a[2],'/tmp/bone.mhd')
        SimpleITK.WriteImage(a[3],'/tmp/connected_bone_'+name)
        #SimpleITK.WriteImage(a[4],'/tmp/connected_bone_no_scp.mhd')
        #SimpleITK.WriteImage(a[5],'/tmp/bones_no_scp.mhd')
        SimpleITK.WriteImage(a[6],'/tmp/rc_'+name)
        SimpleITK.WriteImage(a[6],'/tmp/lung_'+name)
        SimpleITK.WriteImage(get_bounding_box(image, a[6], a[7]), '/tmp/cropped_'+name)
