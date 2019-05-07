#!/usr/bin/python3
"""3D VarDA pipeline. See settings.py for options"""

import numpy as np
import torch
from helpers import VarDataAssimilationPipeline as VarDA
import  AutoEncoders as AE
import sys

sys.path.append('/home/jfm1118')

import utils

import config
from scipy.optimize import minimize

TOL = 1e-3

def main():
    settings = config.Config

    print("alpha =", settings.ALPHA)
    print("obs_var =", settings.OBS_VARIANCE)
    print("obs_frac =", settings.OBS_FRAC)
    print("hist_frac =", settings.HIST_FRAC)
    print("Tol =", TOL)

    #initialize helper function class
    vda = VarDA()

    #The X array should already be saved in settings.X_FP
    #but can be created from .vtu fps if required. see trunc_SVD.py for an example
    X = np.load(settings.X_FP)
    n, M = X.shape

    # Split X into historical and present data. We will
    # assimilate "observations" at a single timestep t_DA
    # which corresponds to the control state u_c
    # We will take initial condition u_0, as mean of historical data
    hist_idx = int(M * settings.HIST_FRAC)
    t_DA = M - settings.TDA_IDX_FROM_END
    assert t_DA > hist_idx, "Cannot select observation from historical data. \
                Reduce HIST_FRAC or reduce TDA_IDX_FROM_END to prevent overlap"

    hist_X = X[:, : hist_idx]
    u_c = X[:, t_DA]
    V, u_0 = vda.create_V_from_X(hist_X, return_mean = True)

    observations, obs_idx, nobs = vda.select_obs(settings.OBS_MODE, u_c, {"fraction": settings.OBS_FRAC}) #options are specific for rand

    #Now define quantities required for 3D-VarDA - see Algorithm 1 in Rossella et al (2019)
    H_0 = vda.create_H(obs_idx, n, nobs)
    d = observations - H_0 @ u_0 #'d' in literature
    #R_inv = vda.create_R_inv(OBS_VARIANCE, nobs)
    if settings.COMPRESSION_METHOD == "SVD":
        V_trunc, U, s, W = vda.trunc_SVD(V, settings.NUMBER_MODES)
        #Define intial w_0
        w_0 = np.zeros((W.shape[-1],)) #TODO - I'm not sure about this - can we assume is it 0?
        # in algorithm 2 we use:

        #OR - Alternatively, use the following:
        # V_plus_trunc = W.T * (1 / s) @  U.T
        # w_0_v2 = V_plus_trunc @ u_0 #i.e. this is the value given in Rossella et al (2019).
        #     #I'm not clear if there is any difference - we are minimizing so expect them to
        #     #be equivalent
        # w_0 = w_0_v2
    elif settings.COMPRESSION_METHOD == "AE":
        import time
        def jacobian(inputs, outputs):
            return torch.stack([torch.autograd.grad([outputs[:, i].sum()], inputs, retain_graph=True, create_graph=True)[0]
                                for i in range(outputs.size(1))], dim=-1)
        latent_size = 2
        kwargs = {"input_size": n, "latent_size": latent_size,"hid_layers":[1000, 200]}
        encoder, decoder = utils.ML_utils.load_AE(AE.VanillaAE, settings.AE_MODEL, **kwargs)
        w_0 = torch.zeros((1, latent_size), requires_grad = True)
        u_0 = decoder(w_0)

        outputs = u_0
        inputs = w_0
        num_grad = 10
        t1 = time.time()
        jac1 = torch.stack([torch.autograd.grad([outputs[:, i].sum()], inputs, retain_graph=True, create_graph=True)[0]
                            for i in range(num_grad)], dim=-1)
        t2 = time.time()
        print("time taken per grad: {:.4f}".format((t2 - t1)/num_grad) )
        print(jac1)
        print(jac1.shape)
        exit()
        jac = jacobian(w_0, u_0)
        print(jac)
        print(jac.shape)


        exit()
        u_0.backward(w_0)
        print(w_0.grad)
        exit()
        x = torch.randn(3, requires_grad=True)


        y = x * 2
        while y.data.norm() < 1000:
            y = y * 2

        print(y)

        v = torch.tensor([0.1, 1.0, 0.0001], dtype=torch.float)
        y.backward(v)

        print(x.grad)
        exit()

    else:
        raise ValueError("COMPRESSION_METHOD must be in {SVD, AE}")

    #Define costJ and grad_J
    args =  (d, H_0, V_trunc, settings.ALPHA, settings.OBS_VARIANCE) # list of all args required for cost_function_J and grad_J
    #args =  (d, H_0, V_trunc, ALPHA, None, R_inv) # list of all args required for cost_function_J and grad_J
    res = minimize(vda.cost_function_J, w_0, args = args, method='L-BFGS-B', jac=vda.grad_J, tol=TOL)

    w_opt = res.x
    delta_u_DA = V_trunc @ w_opt
    u_DA = u_0 + delta_u_DA

    ref_MAE = np.abs(u_0 - u_c)
    da_MAE = np.abs(u_DA - u_c)

    ref_MAE_mean = np.mean(ref_MAE)
    da_MAE_mean = np.mean(da_MAE)

    print("RESULTS")

    print("Reference MAE: ", ref_MAE_mean)
    print("DA MAE: ", da_MAE_mean)
    print("If DA has worked, DA MAE > Ref_MAE")
    #Compare abs(u_0 - u_c).sum() with abs(u_DA - u_c).sum() in paraview

    #Save .vtu files so that I can look @ in paraview
    sample_fp = vda.get_sorted_fps_U(settings.DATA_FP)[0]
    out_fp_ref = settings.INTERMEDIATE_FP + "ref_MAE.vtu"
    out_fp_DA =  settings.INTERMEDIATE_FP + "DA_MAE.vtu"

    vda.save_vtu_file(ref_MAE, "ref_MAE", out_fp_ref, sample_fp)
    vda.save_vtu_file(da_MAE, "DA_MAE", out_fp_DA, sample_fp)


if __name__ == "__main__":
    main()