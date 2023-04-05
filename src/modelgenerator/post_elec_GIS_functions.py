"""
Module: post_elec_GIS_functions
===========================================================================

A module for joining the larger polygons with the electrification algorithm to be able to calculate the demand in Excel

----------------------------------------------------------------------------------------------------------------------------------------

Module author: Nandi Moksnes <nandi@kth.se>

"""
import geopandas as gpd
from geopandas.tools import sjoin
import pandas as pd
import numpy as np
import rasterio
from rasterio.merge import merge
from osgeo import gdal, ogr, gdalconst
import os
import math

def join_elec(elec, tif, cells, scenario):
    """

    :param elec:
    :param tif:
    :param cells:
    :return:
    """
    settlements = gpd.read_file(elec)
    #print(settlements.crs)
    settlements.index = range(len(settlements))
    coords = [(x, y) for x, y in zip(settlements.geometry.x, settlements.geometry.y)]

    _, filename = os.path.split(tif)
    name, ending = os.path.splitext(filename)
    gdp = rasterio.open(tif)
    #print(gdp.crs)
    settlements['GDP_PPP'] = [x[0] for x in gdp.sample(coords)]
    #print(name)

    cell =  gpd.read_file(cells)
    demand_cells = sjoin(settlements, cell, how="left")
    #demand_cells.to_file(os.path.join(os.getcwd(), 'run\scenarios\Demand\demand.shp'))
    demand_cell = pd.DataFrame(demand_cells, copy=True)
    demand_cell.to_csv('run/scenarios/Demand/%i_demand_cells.csv'%(scenario))
    path = 'run/scenarios/Demand/%i_demand_cells.csv'%(scenario)
    return(path)

def network_length(demandcells, input, tofolder, scenario):
    """
    This function calculates the network length for LV which is adapted from van Ruijven et al. 2012 doi:10.1016/j.energy.2011.11.037
    :param demandcells: Includes the data per 1x1km cell
    :param input: Include all parameters needed to run the va Ruijven et al. analysis
    :return:
    """
    network = pd.read_csv(demandcells, header=0)
    input_data = pd.read_csv(input)
    network['Area'] = int( input_data['Area_cell_size'][0])
    network['Inhibited_area'] =input_data['Inhibited_area'][0] #https://lutw.org/wp-content/uploads/Energy-services-for-the-millennium-development-goals.pdf Box II.I The example for disaggregation factor is based on the spread of population in an area.
    network['Household_size'] = input_data['HH'][0]
    network['peak_W'] = input_data['peak(Watt)'][0]
    network['LVarea'] = input_data['LV_area'][0]
    network['capacity'] = input_data['MaxCapacityLV(W)'][0]

    network_list = []
    network['HH'] = network['pop']/network['Household_size']
    network['NRLVs'] = network['HH']*network['peak_W'] /network['capacity']
    network['minLV'] = network['Inhibited_area']/ network['LVarea']
    network['LV_km'] = np.nan
    for i,row in network.iterrows():
        row['HHLV'] = row['HH']/min(row['HH'],max(row['minLV'],row['NRLVs']))
        row['u_length'] = math.sqrt(row['Inhibited_area']/row['HH'])*math.sqrt(2)/2
        row['LVlength'] = 1.333*row['HHLV']*row['u_length']
        row['LV_km'] = row['LVlength']*min(row['HH'] ,max(row['minLV'],row['NRLVs']))

        network_list.append(row)
        ind = row.index

    networkkm = pd.DataFrame(network_list, columns=ind)
    distribution =  networkkm[['elec', 'id', 'LV_km']]
    average_distrbution = distribution[distribution['elec'] == 0]
    distribution_aggr = average_distrbution.groupby(["id"])
    distribution_aggr.mean().reset_index().to_csv(os.path.join(os.getcwd(), tofolder,'%i_distribution.csv' %(scenario)))

    return(os.path.join(os.getcwd(),tofolder,'%i_distribution.csv' %(scenario)))

def elec(demandcells, scenario):
    demand_cell = pd.read_csv(demandcells)

    allcells = demand_cell.groupby(["id"])
    HV_all = allcells.filter(lambda x: (x['elec'].mean() > 0) ) #and ((x['MV'].min() < 1)) or ((x['LV'].min() < 1)) or ((x['Grid'].min() < 1)))
    HV = HV_all.groupby(["id"])
    HV_df = HV.sum(numeric_only=True).reset_index()[['id']]
    HV_df.to_csv(os.path.join(os.getcwd(),'run/%i_HV_cells.csv') %(scenario))

    elec_all = allcells.filter(lambda x: (x['elec'].mean() > 0))
    elec = elec_all.groupby(["id"])
    elec.sum(numeric_only=True).reset_index()[['id']].to_csv(os.path.join(os.getcwd(),'run/%i_elec.csv')%(scenario))
    elec.sum(numeric_only=True).reset_index()[['id']].to_csv(os.path.join(os.getcwd(),'run/scenarios/%i_elec.csv')%(scenario))

    elec_df = elec.sum(numeric_only=True).reset_index()[['id']]
    noHV_elec = (
        pd.merge(elec_df, HV_df, indicator=True, how='outer').query('_merge=="left_only"').drop('_merge', axis=1))
    noHV_elec.to_csv(os.path.join(os.getcwd(), 'run/%i_elec_noHV_cells.csv')%(scenario))

    #noHV_all = allcells.filter()
    #noHV_all = allcells.filter(lambda x: (x['p'].mean() == 0 ) or (x['Minigrid'].min() < 5000) and (x['MV'].min() > 1) or (x['LV'].min() > 1))
    all_pointid = demand_cell['id'].drop_duplicates().dropna()
    noHV = (pd.merge(all_pointid,HV_df, indicator=True, how='outer').query('_merge=="left_only"').drop('_merge', axis=1))
    noHV_nominigrid= (pd.merge(noHV,noHV_elec, indicator=True, how='outer').query('_merge=="left_only"').drop('_merge', axis=1))
    noHV_nominigrid.to_csv(os.path.join(os.getcwd(),'run/%i_noHV_cells.csv')%(scenario))

    minigrid = pd.DataFrame({'id' : [np.nan]})
    minigrid_all = minigrid.groupby(["id"])
    minigrid_all.sum(numeric_only=True).reset_index()[['id']].to_csv(os.path.join(os.getcwd(),'run/%i_minigridcells.csv')%(scenario))

    unelec_all = allcells.filter(lambda x: (x['elec'].mean() == 0 ))
    unelec = unelec_all.groupby(["id"])
    unelec.sum(numeric_only=True).reset_index()[['id']].to_csv(os.path.join(os.getcwd(),'run/%i_un_elec.csv')%(scenario))
    unelec.sum(numeric_only=True).reset_index()[['id']].to_csv(os.path.join(os.getcwd(),'run/scenarios/%i_un_elec.csv')%(scenario))

def calculate_demand(settlements, elecdemand, unelecdemand, scenario, spatial, input_data_csv):
    input_data = pd.read_csv(input_data_csv)
    demand_cell = pd.read_csv(settlements)
    demand_GJ =  elecdemand

    demand_cols =  demand_cell[['elec', 'id', 'pop', 'GDP_PPP']]
    #The case of unelectrified
    un_elec = demand_cols[demand_cols['elec'] == 0]
    unelec_pointid = un_elec.groupby(["id"]).sum()
    unelec_pointid.sum().reset_index()

    sum_pop_unelec = sum(unelec_pointid['pop'])
    un_elec_list= []
    for i, row in unelec_pointid.iterrows():
        row['un_elec_share'] = row['pop']/sum_pop_unelec
        pointid = int(i)
        row['Fuel'] = 'EL3_'+ str(pointid) + '_0'
        startyear = int(input_data['startyear'][0])
        while startyear <=int(input_data['endyear'][0]):
            col = startyear
            row[str(col)] = unelecdemand.iloc[0][col]*row['un_elec_share']
            startyear +=1

        un_elec_list.append(row)
        ind = row.index

    ref_unelec = pd.DataFrame(un_elec_list, columns=ind)

    #The case of electrified
    elec = demand_cols[demand_cols['elec'] == 1]
    elec_pointid = elec.groupby(["id"]).sum()
    elec_pointid.reset_index()

    sum_pop_elec = sum(elec_pointid['pop'])
    sum_gdp_elec = sum(elec_pointid['GDP_PPP'])

    elec_list = []
    for i, row in elec_pointid.iterrows():
        row['elec_share'] = 0.5*row['pop']/sum_pop_elec+0.5*row['GDP_PPP']/sum_gdp_elec
        pointid = int(i)
        row['Fuel'] = 'EL3_'+ str(pointid) + '_1'
        startyear = int(input_data['startyear'][0])
        while startyear <=int(input_data['endyear'][0]):
            col = startyear
            row[str(col)] = elecdemand.iloc[0][col]*row['elec_share']
            startyear +=1
        elec_list.append(row)
        ind = row.index

    ref_elec = pd.DataFrame(elec_list, columns=ind)
    ref = pd.concat(([ref_elec, ref_unelec]))
    ref.index = ref['Fuel']
    ref = ref.drop(columns =['elec', 'pop','GDP_PPP', 'elec_share', 'Fuel', 'un_elec_share'])
    ref.to_csv('run/scenarios/%i_demand_%i_spatialresolution.csv' %(scenario, spatial))

    return ()

def discountrate_csv(discountrate, scenario):
    dr =  pd.read_csv(discountrate)
    dr_scenario = dr[dr['Scenario']==scenario]
    dr_scenario = dr_scenario['Discountrate']
    dr_scenario.to_csv('run/scenarios/%i_discountrate.csv' %(scenario))
