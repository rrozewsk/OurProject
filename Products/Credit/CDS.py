__author__ = 'ryan rozewski'

import Scheduler.Scheduler as schedule
from MonteCarloSimulators.Vasicek.vasicekMCSim import MC_Vasicek_Sim
from Curves.Corporates.CorporateDaily import CorporateRates
from Products.Rates.CouponBond import CouponBond
from Scheduler.Scheduler import Scheduler
from datetime import date
from parameters import xR, t_step,simNumber,Coupon, fee
import pandas as pd
import numpy as np

######################## CDS class ######################################
## Gets Q and Z based on the reference list
## Calculates Zbar(t,t_i) = Q(t,t_i)Z(t,t_i) for t_i in referencedates
## Employs the CouponBond to calculate the present value of the cashflows

######### Potential improvements CDS class ##############################
## 1) CouponBond
##      - Only supports end-of-the-month reference dates and observationdates
##        This is due to the use of getSchedule in Scheduler. Additionally
##        observationdate is defined to be one of the couponsdates. This
##        may be imporved to let observationdate be any date before and after
##        start_date. In order to change this the generators of Q and Z
##        needs to be adjusted.

class CDS(object):
    def __init__(self,start_date,end_date,freq,coupon,referenceDate,rating,R):
        ### Parameters passed to external functions
        self.start_date=start_date
        self.end_date=end_date
        self.freq=freq
        self.R = R
        self.notional = 1
        self.fee =fee
        self.rating = rating
        self.coupon=coupon
        self.referenceDate = referenceDate
        self.observationDate = referenceDate

        ## Get datelist ##
        self.myScheduler = Scheduler()
        ReferenceDateList = self.myScheduler.getSchedule(start=referenceDate,end=end_date,freq=freq, referencedate=referenceDate)

        ## Delay start and maturity
        SixMonthDelay = self.myScheduler.extractDelay("6M")
        TwoYearsDelay = self.myScheduler.extractDelay("2Y")
        ## Delay maturity and start date
        #self.start_date = self.start_date +SixMonthDelay
        self.maturity =self.start_date + TwoYearsDelay

        self.getScheduleComplete()
        portfolioScheduleOfCF = set(ReferenceDateList)
        portfolioScheduleOfCF = portfolioScheduleOfCF.union(self.getScheduleComplete()[0])
        self.portfolioScheduleOfCF = sorted(portfolioScheduleOfCF.union(ReferenceDateList))
        self.ntimes = len(self.datelist)

        self.myZ = None
        self.myQ = None


    #////////////////////////////////////////////////////////////////////////////////////////////#
    #////////////////////////////////////////////////////////////////////////////////////////////#
    #////////////////////////////// SET FUNCTIONS ///////////////////////////////////////////////#
    #////////////////////////////////////////////////////////////////////////////////////////////#
    #////////////////////////////////////////////////////////////////////////////////////////////#

    def setZ(self,Zin):
        ## Zin needs to be a pandas dataframe
        self.myZ = Zin


    def setQ(self,Qin):
        self.myQ = Qin


    #////////////////////////////////////////////////////////////////////////////////////////////#
    #////////////////////////////////////////////////////////////////////////////////////////////#
    #////////////////////////////// GET FUNCTIONS ///////////////////////////////////////////////#
    #////////////////////////////////////////////////////////////////////////////////////////////#
    #////////////////////////////////////////////////////////////////////////////////////////////#

    #//////////////// Get Vasicek simulated Z(t,t_j)
    def getZ_Vasicek(self):
        ### Get Z(t,t_i) for t_i in datelist #####

        ## Simulate Vasicek model with paramters given in workspace.parameters
        vasicekMC = MC_Vasicek_Sim(datelist=[self.start_date,self.end_date], x=xR, simNumber=20, t_step=t_step)
        self.myZ = vasicekMC.getSmallLibor(datelist=self.portfolioScheduleOfCF)
        
        self.myLibor=self.myZ
        self.myZ=self.myZ.loc[:,0]

        ## get Libor Z for reference dates ##
        #self.myZ = vasicekMC.getSmallLibor(datelist= self.portfolioScheduleOfCF)

    #//////////////// Get Corporates simulated Q(t,t_j)
    def getQ_Corporate(self):
        ## Use CorporateDaily to get Q for referencedates ##
        #print("GET Q")
        #print(self.portfolioScheduleOfCF)
        myQ = CorporateRates()
        myQ.getCorporatesFred(trim_start=self.start_date, trim_end=self.end_date)
        ## Return the calculated Q(t,t_i) for bonds ranging over maturities for a given rating
        self.myQ = myQ.getCorporateQData(rating=self.rating, datelist=self.portfolioScheduleOfCF, R=0.4)
        #print(self.myQ.head(10))
        #print("Q finished ")

    #//////////////// Get Premium leg Z(t_i)( Q(t_(i-1)) + Q(t_i) )
    def getPremiumLegZ(self):
        #print("Get premium leg ")
        ## Check if Z and Q exists
        if self.myZ is None:
            self.getZ_Vasicek()

        if self.myQ is None:
            self.getQ_Corporate()


        ## Choose 1month Q
        idx=pd.IndexSlice
        Q1M = self.myQ[self.freq]

        ## Calculate Q(t_i) + Q(t_(i-1))
        Qplus = []
        Qplus.append(Q1M[0])
        for i in range(1,len(Q1M)):
            Qplus.append((Q1M[(i-1)] + Q1M[i])*(self.portfolioScheduleOfCF[i]-self.portfolioScheduleOfCF[i-1]).days/365)

        ## Calculate Z Bar ##
        zbarPremLeg = self.myZ/self.myZ.loc[self.referenceDate]
        for j in range(self.myZ.shape[0]):
            zbarPremLeg.iloc[i] = Qplus[i]*self.myZ.iloc[i]

        ## Calculate the PV of the premium leg using the bond class
        zbarPremLeg=zbarPremLeg.reshape(np.shape(zbarPremLeg)[0],1)
        zbarPremLeg=pd.DataFrame(zbarPremLeg,index=self.myZ.index)
        PVpremiumLeg = self.getExposure(referencedate=self.referenceDate, libor=zbarPremLeg)

        ## Get coupon bond ###
        return PVpremiumLeg

    #//////////////// Get Protection leg Z(t_i)( Q(t_(i-1)) - Q(t_i) )
    def getProtectionLeg(self):
        #print("Get protection leg ")
        if self.myZ is None:
            self.getZ_Vasicek()

        if self.myQ is None:
            self.getQ_Corporate()

        ## Choose 1month Q
        idx=pd.IndexSlice
        Q1M = self.myQ[self.freq]

        ## Calculate Q(t_i) + Q(t_(i-1))
        Qminus = []
        Qminus.append(Q1M[0])
        for i in range(1, len(Q1M)):
            Qminus.append((Q1M[(i - 1)] - Q1M[i])*(self.portfolioScheduleOfCF[i]-self.portfolioScheduleOfCF[i-1]).days/365)


        ## Calculate Z Bar ##
        zbarProtectionLeg = self.myZ / self.myZ.loc[self.referenceDate]
        for i in range(self.myZ.shape[0]):
            zbarProtectionLeg.iloc[ i] = Qminus[i]*self.myZ.iloc[ i]


        ## Calculate the PV of the premium leg using the bond class
        zbarProtectionLeg=zbarProtectionLeg.reshape(np.shape(zbarProtectionLeg)[0],1)
        zbarProtectionLeg=pd.DataFrame(zbarProtectionLeg,index=self.myZ.index)
        PVprotectionLeg = (1-self.R)*self.getExposure(referencedate=self.referenceDate,libor = zbarProtectionLeg)

        ## Get coupon bond ###
        return PVprotectionLeg

    #/////////////////////// Functions to get the exposure sum [delta Z(t,t_j)( Q(t,t_(j-1)) +/- Q(t,t_j) )
    #////// These are copied from Coupon bond
    def getScheduleComplete(self):
        self.datelist = self.myScheduler.getSchedule(start=self.start_date,end=self.maturity,freq=self.freq,referencedate=self.referenceDate)
        self.ntimes = len(self.datelist)
        fullset = list(sorted(list(set(self.datelist)
                                   .union([self.referenceDate])
                                   .union([self.start_date])
                                   .union([self.maturity])
                                   .union([self.observationDate])
                                   )))
        return fullset,self.datelist

    #/////// Get exposure
    def getExposure(self, referencedate,libor):
        self.ntrajectories = np.shape(libor)[1]
        self.ones = np.ones(shape=[self.ntrajectories])
        deltaT = np.zeros(self.ntrajectories)
        if self.ntimes == 0:
            pdzeros = pd.DataFrame(data=np.zeros([1, self.ntrajectories]), index=[referencedate])
            self.pv = pdzeros
            self.pvAvg = 0.0
            self.cashFlows = pdzeros
            self.cashFlowsAvg = 0.0
            return self.pv
        for i in range(1, self.ntimes):
            deltaTrow = ((self.datelist[i] - self.datelist[i - 1]).days / 365) * self.ones
            deltaT = np.vstack((deltaT, deltaTrow))
        self.cashFlows = self.coupon * deltaT
        principal = self.ones
        if self.ntimes > 1:
            self.cashFlows[-1:] += principal
        else:
            self.cashFlows = self.cashFlows + principal
        if (self.datelist[0] <= self.start_date):
            self.cashFlows[0] = -self.fee * self.ones

        if self.ntimes > 1:
            self.cashFlowsAvg = self.cashFlows.mean(axis=1) * self.notional
        else:
            self.cashFlowsAvg = self.cashFlows.mean() * self.notional
        pv = self.cashFlows * libor.loc[self.datelist]
        self.pv = pv.sum(axis=0) * self.notional
        self.pvAvg = np.average(self.pv) * self.notional
        return self.pv

    #///// Get the calculated Market to Market based on spread
    def getValue(self,spread = 1,R = 0,buyer = True):
        ## Assume V(t) = S/2 sum Z(t_i) (Q(t_i) + Q(t_{i-1})) - (1-R)sum Z(t_i) (Q(t_{i-1}) - Q(t_{i}))
        ## Premium leg = S/2 sum Z(t_i) (Q(t_i) + Q(t_{i-1}))
        ## Protection leg =sum Z(t_i) (Q(t_i) + Q(t_{i-1}))
        premiumLeg = self.getPremiumLegZ()
        protectionLeg = self.getProtectionLeg()

        mtm = (spread/2)*premiumLeg - (1-R)*protectionLeg
        if buyer is True:
            return mtm
        else:
            return -mtm

    def getSpread(self):
        return self.getProtectionLeg()/self.getPremiumLegZ()

    def changeGuessForSpread(self,x):
        vasicekMC = MC_Vasicek_Sim(datelist=[self.start_date,self.end_date], x=x, simNumber=20, t_step=t_step)
        self.myQ = vasicekMC.getSmallLibor(datelist=self.portfolioScheduleOfCF)[0]
        self.myQ=pd.DataFrame(self.myQ,index=self.myQ.index)
        self.myQ.columns=[self.freq]
        return self.getSpread()


#### TEST FUNCTIONS ###
'''
# Parameters
t_step = 1.0 / 365.0
simNumber = 10
start_date = date(2005,3,10)
end_date = date(2010,12,31)  # Last Date of the Portfolio
start = date(2005, 3, 10)
referenceDate = date(2005, 3, 10)

# Testing of functions 
testCDS = CDS(start_date = start_date,end_date=end_date,freq="3M",coupon=1,referenceDate=referenceDate,rating="CCC",R=0)
getPremLeg = testCDS.getPremiumLegZ()
getProtectionLeg = testCDS.getProtectionLeg()

print(testCDS.getSpread())
'''