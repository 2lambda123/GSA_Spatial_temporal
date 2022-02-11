# Runs all the GIS-steps for Pathfinder
#
# Author: Nandi Moksnes

# Date: 17 September 2021
# Python version: 3.7


import os
import geopandas as gpd
import gdal
import matplotlib
matplotlib.use('Agg')
import numpy as np
import fiona
import rasterio
import rasterio.mask
import ogr
import pandas as pd
import subprocess

from rasterio.merge import merge
from osgeo import gdal, ogr, gdalconst
gdal.UseExceptions()
#from shapely.geometry import MultiLineString

__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


def convert_zero_to_one(file):
    gpdf = gpd.read_file(file)

    gpdf.loc[(gpdf.elec == 1), 'dijkstra'] = 0 #| ((gpdf.elec ==0) & (gpdf.hrslmultip <= cut_off)),
    gpdf.loc[(gpdf.elec == 0),'dijkstra'] = 1 #& (gpdf.pop >= cut_off))

    gpdf.to_file('../Projected_files/zero_to_one_elec.shp')
    return ('../Projected_files/zero_to_one_elec.shp')

def rasterize_elec(file, proj_path):
    # Rasterizing the point file
    InputVector = file
    _, filename = os.path.split(file)
    name, ending = os.path.splitext(filename)

    OutputImage = os.path.join(proj_path, name + '.tif')

    RefImage = os.path.join('../Projected_files', 'projected_HRSL_2019_UMT37S.tif')

    gdalformat = 'GTiff'
    datatype = gdal.GDT_Int32
    #burnVal = 1  # value for the output image pixels
    # Get projection info from reference image
    Image = gdal.Open(RefImage, gdal.GA_ReadOnly)

    # Open Shapefile
    Shapefile = ogr.Open(InputVector)
    Shapefile_layer = Shapefile.GetLayer()

    # Rasterise
    Output = gdal.GetDriverByName(gdalformat).Create(OutputImage, Image.RasterXSize, Image.RasterYSize, 1, datatype,
                                                     options=['COMPRESS=DEFLATE'])
    Output.SetProjection(Image.GetProjectionRef())
    Output.SetGeoTransform(Image.GetGeoTransform())

    # Write data to band 1
    Band = Output.GetRasterBand(1)
    Band.SetNoDataValue(0)
    gdal.RasterizeLayer(Output, [1], Shapefile_layer, options = ["ATTRIBUTE=dijkstra"])

    # Build image overviews
    subprocess.call("gdaladdo --config COMPRESS_OVERVIEW DEFLATE " + OutputImage + " 2 4 8 16 32 64", shell=True)
    # Close datasets
    Band = None
    Output = None
    Image = None
    Shapefile= None
    return (OutputImage)

def merge_grid(proj_path):
    """This function concatinates the shapefiles which contains the keyword '33kV' and '66kV'

    :param proj_path:
    :return:
    """
    current = os.getcwd()
    os.chdir(proj_path)
    files = os.listdir(proj_path)
    shapefiles = []
    for file in files:
        if file.endswith('.shp'):
            f = os.path.abspath(file)
            shapefiles += [f]
    keyword = ['Concat_MV_lines_UMT37S', 'Concat_Transmission_lines_UMT37S','11kV']
    dijkstraweight = []
    out = [f for f in shapefiles if any(xs in f for xs in keyword)]
    for f in out:
        shpfile = gpd.read_file(f)
        dijkstraweight += [shpfile]

    grid = pd.concat([shp for shp in dijkstraweight], sort=False).pipe(gpd.GeoDataFrame)
    #road = gpd.read_file('../Projected_files/UMT37S_Roads.shp')
    #gdf = grid.append(road)
    grid.to_file("../Projected_files/grid_weight.shp")
    os.chdir(current)
    return("../Projected_files/grid_weight.shp")

def highway_weights(path_grid, path):
    weight_grid = os.path.join(path,'grid_weights.shp')
    weight_highway = os.path.join(path,'road_weights.shp')
    grid = gpd.read_file(path_grid)
    #Length_m_ represents all lines that are grid and Length_km represents road

    keep = ['Length_km', 'Length_m_']
    grid_col = grid[keep]
    pd.options.mode.chained_assignment = None
    grid_col['weight'] = 1
    grid_col = grid_col.astype('float64')
    grid_col.loc[grid_col['Length_km']>0, ['weight']] = 0.01
    grid_col.loc[grid_col['Length_m_']>0, ['weight']] = 0.01

    schema = grid.geometry  #the geometry same as highways
    gdf = gpd.GeoDataFrame(grid_col, crs=32737, geometry=schema)
    gdf.to_file(driver = 'ESRI Shapefile', filename= weight_grid)

    road = gpd.read_file('../Projected_files/UMT37S_Roads.shp')
    keep = ['Length_km']
    highways_col = road[keep]
    pd.options.mode.chained_assignment = None
    highways_col['weight'] = 1
    highways_col = highways_col.astype('float64')
    highways_col.loc[highways_col['Length_km']>0, ['weight']] = 0.5

    schema = road.geometry  #the geometry same as highways
    gdf_road = gpd.GeoDataFrame(highways_col, crs=32737, geometry=schema)
    gdf_road.to_file(driver = 'ESRI Shapefile', filename= weight_highway)


    return (weight_highway, weight_grid)

# Pathfinder results to raster
def make_raster(pathfinder, s):
    dst_filename = os.path.join('temp/dijkstra','path_%s.tif' %(s))
    path = os.path.join('../Projected_files','%s_elec.tif' %(s))
    zoom_20 = gdal.Open(path)
    geo_trans = zoom_20.GetGeoTransform()
    pixel_width = geo_trans[1]

    # You need to get those values like you did.
    x_pixels = zoom_20.RasterXSize  # number of pixels in x
    y_pixels = zoom_20.RasterYSize # number of pixels in y
    PIXEL_SIZE = -geo_trans[5]  # size of the pixel...
    x_min = geo_trans[0]
    y_max = geo_trans[3]
    wkt_projection = zoom_20.GetProjection()

    driver = gdal.GetDriverByName('GTiff')
    dataset3 = driver.Create(
        dst_filename,
        x_pixels,
        y_pixels,
        1,
        gdal.GDT_Float32 )

    dataset3.SetGeoTransform((
        x_min, PIXEL_SIZE,
        0,
        y_max,
        0,
        -PIXEL_SIZE))

    dataset3.SetProjection(wkt_projection)
    dataset3.GetRasterBand(1).WriteArray(pathfinder)
    dataset3.FlushCache()  # Write to disk.
    return dst_filename

def make_weight_numpyarray(file, s):
    raster = gdal.Open(file)
    weight = raster.ReadAsArray()
    NoValue = weight < -3.4*10**38  #related to GDAL which sets NoValue to -3.4e+38
    weight[NoValue] = 1

    #Pathfinder cannot handle tagerts that are on the edge, therefore two extra rows and columns is added (on top and bottom) as all need to have the same shape
    if np.count_nonzero(weight) != 0:
        b = np.ones((weight.shape[0], weight.shape[1] + 2))
        b[:, 1:-1] = weight
        c = np.ones((b.shape[0] +2, b.shape[1]))
        c[1:-1,:] = b
        np.savetxt(os.path.join('temp/dijkstra', "%s_weight.csv" %(s)), c, delimiter=',')
    raster = None # close the raster

    return None

def make_origin_numpyarray(file, s):
    nparray = np.genfromtxt((file), delimiter=',')
    row = int(round(nparray.shape[0]/2))
    col = int(round(nparray.shape[1]/2))
    origins = np.zeros(nparray.shape)

    if nparray[row, col] == 0:
        origins[row,col] = 1
    else:
        origin_found = False
        maxrow = nparray.shape[0] - row-1
        maxcol = nparray.shape[1] - col-1
        j = row
        for i in (range(1, maxrow)):
            j = j +1
            k = col
            for m in (range(1, maxcol)):
                if origin_found == True:
                    break
                k = k + 1
                if nparray[j, k] == 0:
                    origins[j, k] = 1
                    origin_found = True
                    break
            #if nparray[j, col] == 0:
             #   origins[j,col] = 1
             #   origin_found = True
             #   break

        j = row
        for i in (range(1, maxrow)):
            if origin_found == True:
                break
            j = j -1
            k = col
            for m in (range(1, maxcol)):
                if origin_found == True:
                    break
                k = k - 1
                if nparray[j, k] == 0:
                    origins[j, k] = 1
                    origin_found = True
            #if nparray[j, col] == 0:
             #   origins[j,col] = 1
              #  origin_found = True
              #  break
    if np.count_nonzero(origins) != 0:
        np.savetxt(os.path.join('temp/dijkstra', "%s_origin.csv" %(s)), origins, delimiter=',')
    return None

def make_target_numpyarray(file, s):
    raster = gdal.Open(file)
    target = raster.ReadAsArray()
    NoValue = target > 2
    target[NoValue] = 0

    #Pathfinder cannot handle tagerts that are on the edge, therefore two extra rows and columns is added (on top and bottom)
    if np.count_nonzero(target) != 0:
        b = np.zeros((target.shape[0], target.shape[1] + 2))
        b[:,1 :-1] = target
        c = np.zeros((b.shape[0] +2, b.shape[1]))
        c[1:-1,:] = b
        np.savetxt(os.path.join('temp/dijkstra', "%s_target.csv" %(s)), c, delimiter=',')
    raster = None # close the raster

    return os.path.join('temp/dijkstra', "%s_target.csv" %(s))

def rasterize_road(file, proj_path):
    # Rasterizing the point file
    InputVector = file
    #_, filename = os.path.split(file)
    #name, ending = os.path.splitext(filename)
    OutputImage2 = os.path.join(proj_path, 'road.tif')
    RefImage = os.path.join('../Projected_files', 'projected_HRSL_2019_UMT37S.tif')

    gdalformat = 'GTiff'
    datatype2 = gdal.GDT_Float32
    burnVal = 1  # value for the output image pixels
    # Get projection info from reference image
    Image2 = gdal.Open(RefImage, gdal.GA_ReadOnly)

    # Open Shapefile
    Shapefile = ogr.Open(InputVector)
    Shapefile_layer = Shapefile.GetLayer()

    # Rasterise
    Output2 = gdal.GetDriverByName(gdalformat).Create(OutputImage2, Image2.RasterXSize, Image2.RasterYSize, 1, datatype2, options=['COMPRESS=DEFLATE'] ) #
    Output2.SetProjection(Image2.GetProjectionRef())
    Output2.SetGeoTransform(Image2.GetGeoTransform())

    # Write data to band 1
    band2 = Output2.GetRasterBand(1)
    band2.SetNoDataValue(1)
    gdal.RasterizeLayer(Output2, [1], Shapefile_layer, options = ["ATTRIBUTE=weight"])

    # Build image overviews
    subprocess.call("gdaladdo --config COMPRESS_OVERVIEW DEFLATE " + OutputImage2 + " 2 4 8 16 32 64", shell=True)
    # Close datasets
    band2 = None
    Output2 = None
    Image2 = None
    Shapefile = None

    return OutputImage2

def rasterize_transmission(file, proj_path):
    # Rasterizing the point file
    InputVector = file
    #_, filename = os.path.split(file)
    #name, ending = os.path.splitext(filename)
    OutputImage3 = os.path.join(proj_path, 'transmission.tif')
    RefImage = os.path.join('../Projected_files', 'projected_HRSL_2019_UMT37S.tif')

    gdalformat = 'GTiff'
    datatype2 = gdal.GDT_Float32
    burnVal = 1  # value for the output image pixels
    # Get projection info from reference image
    Image2 = gdal.Open(RefImage, gdal.GA_ReadOnly)

    # Open Shapefile
    Shapefile = ogr.Open(InputVector)
    Shapefile_layer = Shapefile.GetLayer()

    # Rasterise
    Output2 = gdal.GetDriverByName(gdalformat).Create(OutputImage3, Image2.RasterXSize, Image2.RasterYSize, 1, datatype2, options=['COMPRESS=DEFLATE'] ) #
    Output2.SetProjection(Image2.GetProjectionRef())
    Output2.SetGeoTransform(Image2.GetGeoTransform())

    # Write data to band 1
    band2 = Output2.GetRasterBand(1)
    band2.SetNoDataValue(1)
    gdal.RasterizeLayer(Output2, [1], Shapefile_layer, options = ["ATTRIBUTE=weight"])

    # Build image overviews
    subprocess.call("gdaladdo --config COMPRESS_OVERVIEW DEFLATE " + OutputImage3 + " 2 4 8 16 32 64", shell=True)
    # Close datasets
    band2 = None
    Output2 = None
    Image2 = None
    Shapefile = None

    return OutputImage3

def merge_raster(transmission_raster, highway_raster):
    out_fp = '../Projected_files/weights.tif'
    transmission = rasterio.open(transmission_raster)
    road = rasterio.open(highway_raster)

    def custom_merge_works(old_data, new_data, old_nodata, new_nodata, index=None, roff=None, coff=None):
        old_data[:] = np.minimum(old_data, new_data)  # <== NOTE old_data[:] updates the old data array *in place*

    weights, out_trans = merge([transmission, road], method=(custom_merge_works))
    out_meta = transmission.meta.copy()
    out_meta.update({"driver": "GTiff","height": weights.shape[1],"width": weights.shape[2],"transform": out_trans,"crs":32737})

    with rasterio.open(out_fp, "w", **out_meta) as dest:
        dest.write(weights)

    return out_fp

def removing_grid(elec_path, weights):
    if elec_path.shape == weights.shape:
        row = range(1,elec_path.shape[0])
        col = range(1,elec_path.shape[1])
        i = 0
        for i in row:
            j = 0
            for j in col:
                if weights[i][j] < 0.45:
                    elec_path[i][j] =0
                j += 1
            i += 1

    return elec_path

def masking(shape,tif_file, s):
    """ This function masks the raster data (tif-file) with the GADM Admin 0 boundaries (admin)
    :param bounds:
    :param tif_file:
    :return: tif_file
    """

    with fiona.open(shape, "r") as shapefile:
        shapes = [feature["geometry"] for feature in shapefile]
    with rasterio.open(tif_file) as src:
        out_image, out_transform = rasterio.mask.mask(src, shapes, crop=True)
        out_meta = src.meta
    out_meta.update({"driver": "GTiff",
                     "height": out_image.shape[1],
                     "width": out_image.shape[2],
                     "transform": out_transform})

    with rasterio.open('../Projected_files/%s' %(s), "w", **out_meta) as dest:
        dest.write(out_image)
    return('../Projected_files/%s' %(s))