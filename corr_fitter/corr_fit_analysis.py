import time
import sys
import lsqfit
import h5py as h5
import os
import pandas as pd
import numpy as np
import gvar as gv
import matplotlib
import importlib
import matplotlib.pyplot as plt
import matplotlib.mlab as mlab
import matplotlib.colors as colors
from matplotlib.backends.backend_pdf import PdfPages
import tqdm
from multiprocessing import Pool
from functools import partial
from copy import deepcopy

from   corr_fitter.corr_fitter import Fitter
import corr_fitter.load_data_priors as ld


def analyze_hyperon_corrs(file_path, fit_params_path,corrs,n_states,t_range,t_start, t_end,pdf_name, model_type: str, bs: bool = False, bs_file: str = None,
                          bs_path: str = None, bs_N: int = None, bs_seed: str = None, show_eff=True,show_stab=True,best_fit_t_idx=None,
                          t_plot_min=None, t_plot_max=None, show_fit=True,n_states_array= None):
    '''A wrapper to perform final analysis of hyperon spectrum'''
    sys.path.append(os.path.dirname(os.path.abspath(fit_params_path)))
    fp = importlib.import_module(fit_params_path.split('/')[-1].split('.py')[0])
    p_dict = fp.p_dict
    prior = fp.prior
    nstates_list = [1,2,3,4]
    # for nstate in nstates_list:
    all_baryons = {}
    t = np.arange(t_start, 13)
    corrs_copy = deepcopy(corrs)  # need this or else gvars are passed to gv.dataset.avg_data() on subsequent runs of t_range
    fit_analysis = Fitter_Analysis(t_range=t_range, simult=True, t_period=64,
                                        states=p_dict['hyperons'], p_dict=p_dict, n_states=n_states,
                                        prior=prior, corr_gv=corrs_copy, model_type=model_type)
    print(fit_analysis.get_fit())
    if show_stab:
            # fit_analysis.plot_stability(all_baryons,pdf_name,best_fit_t_idx,n_states_array=n_states_array)
            fit_analysis.plot_stability(pdf_name,t_start=5,t_end=25,model_type=model_type,n_states_array=nstates_list)
    for ti in t:
        t_range = [ti, t_end]
        corrs_copy = deepcopy(corrs)  # need this or else gvars are passed to gv.dataset.avg_data() on subsequent runs of t_range
        fit_analysis = Fitter_Analysis(t_range=t_range, simult=True, t_period=64,
                                        states=p_dict['hyperons'], p_dict=p_dict, n_states={'hyperons': 2},
                                        prior=prior, corr_gv=corrs_copy, model_type=model_type)
            # print(fit_analysis.get_fit(t_range,nstates_list)
        # fit_result = fit_analysis.get_fit_forstab(t_range=t_range)
        # all_baryons[ti] = fit_result
        # print(f"Fit result for t_range {t_range}: \n {fit_result}")
        

    if show_eff:
        corrs_copy = deepcopy(corrs)  # need this or else gvars are passed to gv.dataset.avg_data() on subsequent runs of t_range
        fit_analysis_single_trange = Fitter_Analysis(t_range=p_dict['t_range'], simult=True, t_period=64,
                                        states=p_dict['hyperons'], p_dict=p_dict, n_states={'hyperons': 2},
                                        prior=prior, corr_gv=corrs_copy, model_type=model_type)
        fit_analysis_single_trange.plot_effective_mass(t_plot_min=t_plot_min, t_plot_max=t_plot_max,
                                            model_type=model_type, show_fit=show_fit)

    # return my_fit
    # run bootstrapping routine -> bootstrapped h5 file based on baryon fit posterior
    if bs:
        def fast_resample_correlator(corr, bs_seed, bs_N):
            bs_M = corrs['lam']['SS'].shape[0]
            bs_list = np.random.randint(low=0, high=bs_M, size=(bs_N, bs_M))
            
            resampled_raw_corr_data = {key: corr[key][bs_list[n, :], :] for key in corr.keys() for n in range(bs_N)}
            fit_parameters_keys = sorted(hyperon_fit.p.keys())
            return {key: [] for key in fit_parameters_keys}, resampled_raw_corr_data
            
        bs_N = range(bs_N)
        bs_list = np.random.randint(low=0, high=bs_M, size=(bs_N, bs_M))


        def parallel_resample_correlator(bs_list, correlators, j):
            correlators_bs = {}
            for r in correlators:
                correlator_bs = fast_resample_correlator(correlators[r], bs_list, j)
                correlators_bs[r] = correlator_bs
            return correlators_bs

        with Pool(processes=4) as p:
            output = {key: [] for key in hyperon_fit.keys()}
            results = p.imap_unordered(partial(parallel_resample_correlator, bs_list), bs_N)

            # iterate with tqdm only once for faster performance
            for i in tqdm.tqdm(results, total=len(bs_N), desc='making fit with resampled hyperon correlators'):
                all_baryons_bs = Fitter_Analysis(t_range=p_dict['t_range'], simult=True, t_period=64, states=p_dict['hyperons'], p_dict=p_dict,
                                                    n_states=p_dict['n_states'], prior=prior, corr_gv=i, model_type="all")

                temp_fit = all_baryons_bs.get_fit()
                for key in hyperon_fit.keys():
                    p = temp_fit.pmean[key]
                    output[key].append(p)

        table = gv.dataset.avg_data(output, bstrap=True)
        print('\n\n', gv.tabulate(table))

        post_bs = {}

        for r in output:
            output[r]  = np.array(output[r])

        with h5.File(bs_file, 'a') as f5:
            try:
                f5.create_group(bs_path)
            except Exception as e:
                print(e)
            for r in output:
                if len(output[r]) > 0:
                    if r in f5[bs_path]:
                        del f5[bs_path+'/'+r]
                    f5.create_dataset(bs_path+'/'+r, data=output[r])

    else:
        return all_baryons

class Fitter_Analysis(object):
    def __init__(self, t_period, prior,p_dict,t_range, n_states=None, model_type = None,states=None,simult=None,
                 corr_gv=None):
        #Convert correlator data into gvar dictionaries
        if corr_gv is not None:
            for key, value in corr_gv.items():
                corr_gv[key] = gv.dataset.avg_data(value)
        else:
            corr_gv = None
        # Default to a 1 state fit
        if n_states is None:
            n_states = 1

        for data_gv in [corr_gv]:
            if data_gv is not None:
                t_max = len(data_gv[list(data_gv.keys())[0]])

        if isinstance(t_range,list): # for running multiple fit ranges not based on input file t_ranges
            t_start = t_range[0]
            t_end = t_range[1]
        else:
            t_start = np.min([t_range[key][0] for key in list(t_range.keys())])
            t_end = np.max([t_range[key][1] for key in list(t_range.keys())])

        if isinstance(n_states, int):
            max_n_states = n_states
        else:
            # max_n_states = np.max([n_states[key] for key in list(n_states.keys())])
            max_n_states = 4
        self.p_dict = p_dict
        self.model_type = model_type
        self.corr_gv = corr_gv
        self.states=states 
        self.simult = simult
        self.n_states = n_states
        self.prior = prior
        self.t_range = t_range
        self.t_period = t_period
        self.t_delta = 2*max_n_states
        self.t_min = int(t_start/2)
        self.t_max = int(np.min([t_end, t_end]))
        self.fits = {}
        
        #self.bs = None

    def plot_stability(self,pdf_filename,t_start=None,t_end=None,model_type=None,best_fit_t_idx=None,n_states_array=None):
        with PdfPages(pdf_filename) as pdf:
            nstates_list = [1,2,3,4]
            colors = ['b', 'g', 'r', 'c', 'm', 'y', 'k']
            markers = ['o', 's', '^', 'v', 'D', 'P', 'X']
            fit_data = {}
            if n_states_array is None:
                fit_data[self.n_states[model_type]] = None
            else:
                for n_state in n_states_array:
                    fit_data[n_state] = {}

            if n_states_array is None:
                spacing = [0]
            else:
                spacing = (np.arange(len(n_states_array)) - (len(n_states_array)-1)/2.0)/((len(n_states_array)-1)/2.0) *0.25

            for particle_idx, particle in enumerate(self.p_dict['tag'].keys()):
                fit_data[particle] = {}
                fig, axs = plt.subplots(1, 2, figsize=(15, 5))
                fig.suptitle(self.p_dict['abbr'] + ' - ' + particle, fontsize=24, y=1.05)
                for key in list(fit_data.keys()):
                    fit_data[particle][key] = {
                    'y' : np.array([]),
                    'chi2/df' : np.array([]),
                    'Q' : np.array([]),
                    't' : np.array([])
                }
                for n_state in list(fit_data.keys()):
                    n_states_dict = self.n_states.copy()
                    n_states_dict[model_type] = n_state
                    t = np.arange(t_start, 13)
                    for ti in t:
                        t_range = {key : self.t_range[key] for key in list(self.t_range.keys())}

                        t_range[model_type] = [ti, t_end]
    
                        temp_fit = self.get_fit_forstab(t_range,n_states_dict)
                        fit_data[particle][n_state]['y'] = np.append(fit_data[particle][n_state]['y'], temp_fit.p[particle+'_E0'])
                
                        fit_data[particle][n_state]['chi2/df'] = np.append(fit_data[particle][n_state]['chi2/df'], temp_fit.chi2 / temp_fit.dof)
                        fit_data[particle][n_state]['Q'] = np.append(fit_data[particle][n_state]['Q'], temp_fit.Q)
                        fit_data[particle][n_state]['t'] = np.append(fit_data[particle][n_state]['t'], t)
            print(fit_data)
                #         fit_analysis = Fitter_Analysis(t_range=t_range, simult=True, t_period=64,
                #                                         states=p_dict['hyperons'], p_dict=p_dict, n_states={'hyperons': 2},
                #                                         prior=prior, corr_gv=corrs_copy, model_type=model_type)
                #         fit_result = fit_analysis.get_fit_forstab(t_range=t_range)
                    
                # # t_values = []
                # # E0_values = []
                # # E0_errors = []
                # # q_values = []
                # # chi_sq_values = []

                #     for t, fit_result in all_baryons.items():
                #         fit_data[n_state]['y'] = np.append(fit_data[particle][n_state]['y'], fit_result.p[particle+'_E0'])
                
                #         fit_data[n_state]['chi2/df'] = np.append(fit_data[particle][n_state]['chi2/df'], fit_result.chi2 / fit_result.dof)
                #         fit_data[n_state]['Q'] = np.append(fit_data[particle][n_state]['Q'], fit_result.Q)
                #         fit_data[n_state]['t'] = np.append(fit_data[particle][n_state]['t'], t)
                #     # t_values.append(t)
                #     # E0_values.append(fit_result.p[particle+'_E0'].mean)
                #     # E0_errors.append(fit_result.p[particle+'_E0'].sdev)
                #     # q_values.append(fit_result.Q)
                #     # chi_sq_values.append(fit_result.chi2 / fit_result.dof)
                # # print(E0_values,"e0")
                # # print(t_values)
                # # Best fit band
                # print(fit_data)
                # for i, n_state in enumerate(sorted(fit_data.keys())):
                #     for j, ti in enumerate(fit_data[n_state]['t']):
                #         print(i,n_state)
                # if best_fit_t_idx is None:
                #     best_fit_idx = np.argmin(chi_sq_values)
                # else:
                #     best_fit_idx = t_values.index(best_fit_t_idx)
                # # best_fit = self.get_fit_forstab()
                # best_fit_E0 = E0_values[best_fit_idx]
                # # best_fit_E0 = best_fit.p[particle+'_E0']
                # tp = np.arange(t_values[0] - 1, t_values[-1] + 2)
                # y2 = np.repeat(best_fit_E0, len(tp))
                # y2_upper = np.repeat(best_fit_E0 + E0_errors[best_fit_idx], len(tp))
                # y2_lower = np.repeat(best_fit_E0 - E0_errors[best_fit_idx], len(tp))
                # axs[0].plot(tp, y2, '--', color=colors[particle_idx % len(colors)])
                # axs[0].fill_between(tp, y2_lower, y2_upper, facecolor=colors[particle_idx % len(colors)], alpha=0.25)


                # # Plot E0 fit parameters with error bars
                # axs[0].errorbar(t_values, E0_values, yerr=E0_errors, fmt=markers[particle_idx % len(markers)], color=colors[particle_idx % len(colors)], label=particle)
                # axs[0].set_title('Hyperon stability plot for n=2 states')
                # axs[0].set_ylabel('E0 fit parameter')
                # axs[0].legend()

                # # Q-value plot
                # ax = axs[1]
                # ax.plot(t_values, q_values, marker='o', linestyle='')
                # ax.set_xlabel('Starting time slice')
                # ax.set_ylabel('Q-value')

                # # Chi2/dof color map
                # cmap = matplotlib.cm.get_cmap('rainbow')
                # norm = matplotlib.colors.Normalize(vmin=0.25, vmax=1.75)
                # chi2_dof_values = [fit_result.chi2 / fit_result.dof for t, fit_result in all_baryons.items()]
                # colors = [cmap(norm(chi2_dof)) for chi2_dof in chi2_dof_values]

                # for t, chi2_dof, color in zip(t_values, chi2_dof_values, colors):
                #     rect = plt.Rectangle((t - 0.5, 0), 1, chi2_dof, color=color)
                #     axs[1].add_patch(rect)

                # cax = fig.add_axes([0.95, 0.15, 0.02,0.7])
                # colorbar = matplotlib.colorbar.ColorbarBase(cax, cmap=cmap, norm=norm, orientation='vertical')
                # colorbar.set_label(r'$\chi^2_\nu$', fontsize=24) 
                # pdf.savefig(fig, bbox_inches='tight') 
                # plt.close(fig)  
                # plt.show()

    def get_fit_forstab(self, t_range=None, n_states=None,t_period=None):
        if t_range is None:
            t_range = self.t_range
        if n_states is None:
            n_states = self.n_states
        if t_period is None:
            t_period = self.t_period
        
        temp_fit = Fitter(n_states=n_states,prior=self.prior,p_dict=self.p_dict, 
                            t_range=t_range,states=self.states,simult=self.simult,
                            t_period=t_period,model_type=self.model_type, raw_corrs=self.corr_gv).get_fit()
    
        return temp_fit

    def get_fit(self, t_range=None, n_states=None,t_period=None):
        if t_range is None:
            t_range = self.t_range
        if n_states is None:
            n_states = self.n_states
        if t_period is None:
            t_period = self.t_period

        index = tuple((t_range[key][0], t_range[key][1], n_states[key]) for key in sorted(t_range.keys()))
        # index = tuple((t_range[0], t_range[1], n_states[key]) for key in sorted(n_states.keys()))

        if index in list(self.fits.keys()):
            return self.fits[index]
        # if verbose:
        #     print(f"Using existing fit for index: {index}")
        else:
            temp_fit = Fitter(n_states=n_states,prior=self.prior,p_dict=self.p_dict, 
                            t_range=t_range,states=self.states,simult=self.simult,
                            t_period=t_period,model_type=self.model_type, raw_corrs=self.corr_gv).get_fit()
    
            self.fits[index] = temp_fit
            # if verbose:
            #     print(f"Created new fit for index: {index}")
            return temp_fit
        
    def _get_models(self, model_type=None):
        if model_type is None:
            return None
        # t=list(range(self.t_range[self.model_type][0], self.t_range[self.model_type][1]))

        return Fitter(
            n_states=self.n_states, states=self.states,prior=self.prior,simult=self.simult, p_dict=self.p_dict, 
            t_range=self.t_range,t_period=self.t_period,model_type=self.model_type,raw_corrs=self.corr_gv
            )._make_models_simult_fit()
    

    def _generate_data_from_fit(self, t, t_range=None,t_start=None, t_end=None, model_type=None, n_states=None):
        if model_type is None:
            return None
    
        if t_start is None:
            t_start = self.t_range[model_type][0]
        if t_end is None:
            t_end = self.t_range[model_type][1]
        if n_states is None:
            n_states = self.n_states

        t_range = {key : self.t_range[key] for key in list(self.t_range.keys())}
        t_range[model_type] = [t_start, t_end]

        models = self._get_models(model_type=model_type)
        fit = self.get_fit(t_range=t_range, n_states=n_states)

        output = {model.datatag : model.fitfcn(p=fit.p, t=t) for model in models}
        return output


    def compute_eff_mass(self, corr_gv=None, dt=None):
        if corr_gv is None:
            corr_gv = self.corr_gv
        if dt is None:
            dt = 1
        eff_mass = {}
        if len(corr_gv.keys()) == 14: #dont hardcode this 
            for key in corr_gv:
                eff_mass[key] = 1/dt * np.log(corr_gv[key] / np.roll(corr_gv[key], -1))
        else:
            for corr in corr_gv:
                eff_mass[corr] = {}
                for key in corr_gv[corr]:
                    eff_mass[corr][key] = 1/dt * np.log(corr_gv[corr][key] / np.roll(corr_gv[corr][key], -1))
                
        return eff_mass

    def plot_effective_mass(self, t_plot_min=None, model_type=None,
                            t_plot_max=None, show_plot=True, show_fit=True, fig_name=None):
        if t_plot_min is None:
            t_plot_min = self.t_min
        if t_plot_max is None:
            t_plot_max = self.t_max
        markers = ["o", "s"]
        colors = np.array(['tab:red', 'tab:blue', 'tab:green', 'tab:purple', 'tab:orange', 'tab:brown',
                        'tab:pink', 'tab:gray', 'tab:olive', 'tab:cyan'])
    
        t = np.arange(t_plot_min, t_plot_max)

        effective_mass = {}

        if self.corr_gv is None:
            raise TypeError('you need to supply a correlator model in order to generate an eff mass plot for that correlator')

        effective_mass = self.compute_eff_mass(self.corr_gv)
        print(effective_mass)

        y = {}
        y_err = {}
        lower_quantile = np.inf
        upper_quantile = -np.inf
        for i, baryon in enumerate(effective_mass.keys()):
            y[baryon] = {}
            y_err[baryon] = {}
            for j, key in enumerate(effective_mass[baryon].keys()):
                y[baryon][key] = gv.mean(effective_mass[baryon][key])[t]
                y_err[baryon][key] = gv.sdev(effective_mass[baryon][key])[t]
                lower_quantile = np.min([np.nanpercentile(y[baryon][key], 25), lower_quantile])
                upper_quantile = np.max([np.nanpercentile(y[baryon][key], 75), upper_quantile])

                plt.errorbar(x=t, y=y[baryon][key], xerr=0.0, yerr=y_err[baryon][key], fmt=markers[j % len(markers)], capsize=4.0,
                            color=colors[i % len(colors)], capthick=1.0, alpha=0.3, elinewidth=2.0,
                            label=baryon + '_' + key, markersize=5, markeredgecolor='black')
            delta_quantile = upper_quantile - lower_quantile
            plt.ylim(lower_quantile - 0.5 * delta_quantile,
                    upper_quantile + 0.5 * delta_quantile)

        if show_fit:
            t = np.linspace(t_plot_min - 2, t_plot_max + 2)
            dt = (t[-1] - t[0]) / (len(t) - 1)
            fit_data_gv = self._generate_data_from_fit(model_type=model_type, t=t)
            eff_mass_fit = {}
            for j, key in enumerate(fit_data_gv.keys()):
                eff_mass_fit = self.compute_eff_mass(fit_data_gv, dt)[key][1:-1]

                pm = lambda x, k: gv.mean(x) + k * gv.sdev(x)
                plt.plot(t[1:-1], pm(eff_mass_fit, 0), '--', color=colors[j % len(colors)])
                plt.plot(t[1:-1], pm(eff_mass_fit, 1), t[1:-1], pm(eff_mass_fit, -1), color=colors[j % len(colors)])
                plt.fill_between(t[1:-1], pm(eff_mass_fit, -1), pm(eff_mass_fit, 1),facecolor=colors[j % len(colors)], alpha=0.10, rasterized=True)
            plt.title("Simultaneous fit to %d baryons for $N_{states} = $%s" % (len(effective_mass), self.n_states['hyperons']), fontsize=18)

            plt.xlim(t_plot_min - 0.5, t_plot_max - 0.5)
            plt.ylim(0.3, 1.3)

            # Get unique markers when making legend
            handles, labels = plt.gca().get_legend_handles_labels()
            temp = {}
            for j, handle in enumerate(handles):
                temp[labels[j]] = handle

            legend = plt.legend([temp[label] for label in sorted(temp.keys())], [label for label in sorted(temp.keys())], fontsize='x-small')
            legend.set_bbox_to_anchor((1.05, 1))

            plt.grid(True)
            plt.xlabel('$t$', fontsize=24)
            plt.ylabel('$M^{eff}_{baryon}$', fontsize=24)
            fig = plt.gcf()
            fig.set_size_inches(12, 7)

            if show_plot:
                plt.show()
            else:
                plt.close()

            return fig
    

    # def plot_stability(self, model_type=None, t_start=None, t_end=None, t_middle=None, vary_start=False, show_plot=True, n_states_array=None,fig_name=None):

    #     # Set axes: first for quantity of interest (eg, E0)
    #     ax = plt.axes([0.10,0.20,0.7,0.7])

    #     # Markers for identifying n_states
    #     markers = ["^", ">", "v", "<"]

    #     # Color error bars by chi^2/dof
    #     cmap = matplotlib.cm.get_cmap('rainbow_r')
    #     norm = matplotlib.colors.Normalize(vmin=0.25, vmax=1.75)

    #     fit_data = {}
    #     if n_states_array is None:
    #         fit_data[self.n_states[model_type]] = None
    #     else:
    #         for n_state in n_states_array:
    #             fit_data[n_state] = None

    #     if n_states_array is None:
    #         spacing = [0]
    #     else:
    #         spacing = (np.arange(len(n_states_array)) - (len(n_states_array)-1)/2.0)/((len(n_states_array)-1)/2.0) *0.25

    #     # Make fits from [t, t_end], where t is >= t_end
    #     if vary_start:
    #         if t_start is None:
    #             t_start = self.t_min

    #         if t_end is None:
    #             t_end = self.t_range[model_type][1]

    #         if t_middle is None:
    #             t_middle = int((t_start + 2*t_end)/3)

    #         plt.title("Stability plot, varying start\n Fitting [%s, %s], $N_{states} =$ %s"
    #                   %("$t$", t_end, sorted(fit_data.keys())), fontsize = 24)

    #         t = np.arange(t_start, t_middle + 1)
    #         print(t,"opt_t")

    #     # Vary end point instead
    #     else:
    #         if t_start is None:
    #             t_start = self.t_range[model_type][0]

    #         if t_end is None:
    #             t_end = self.t_max

    #         if t_middle is None:
    #             t_middle = int((2*t_start + t_end)/3)

    #         plt.title("Stability plot, varying end\n Fitting [%s, %s], $N_{states} =$ %s"
    #                   %(t_start, "$t$", sorted(fit_data.keys())), fontsize = 24)
    #         t = np.arange(t_middle, t_end + 1)

    #     for key in list(fit_data.keys()):
    #         fit_data[key] = {
    #             'y' : np.array([]),
    #             'chi2/df' : np.array([]),
    #             'Q' : np.array([]),
    #             't' : np.array([])
    #         }

    #     for n_state in list(fit_data.keys()):
    #         n_states_dict = self.n_states.copy()
    #         n_states_dict[model_type] = n_state
    #         for ti in t:
    #             t_range = {key : self.t_range[key] for key in list(self.t_range.keys())}
    #             if vary_start:
    #                 t_range[model_type] = [ti, t_end]
    #                 temp_fit = self.get_fit(t_range, n_states_dict)
    #             else:
    #                 t_range[model_type] = [t_start, ti]
    #                 temp_fit = self.get_fit(t_range, n_states_dict)
    #             # print(f"t_range: {t_range}")  # Add this print statement
    #             # print(f"n_states_dict: {n_states_dict}")  # Add th
    #             # temp_fit = self.get_fit(t_range, n_states_dict)
    #             if temp_fit is not None:
    #                 for corr in self.p_dict['particles']:
    #                     fit_data[n_state]['y'] = np.append(fit_data[n_state]['y'], temp_fit.p[corr+'_E0'])
    #                     fit_data[n_state]['chi2/df'] = np.append(fit_data[n_state]['chi2/df'], temp_fit.chi2 / temp_fit.dof)
    #                     fit_data[n_state]['Q'] = np.append(fit_data[n_state]['Q'], temp_fit.Q)
    #                     fit_data[n_state]['t'] = np.append(fit_data[n_state]['t'], ti)

    #                     print("temp_fit.p[corr+'_E0']:", temp_fit.p[corr+'_E0'])
    #                     print("fit_data[n_state]['y']:", fit_data[n_state]['y'])



    #         # Color map for chi/df
    #         cmap = matplotlib.cm.get_cmap('rainbow')
    #         min_max = lambda x : [np.min(x), np.max(x)]
    #         #minimum, maximum = min_max(fit_data['chi2/df'])
    #         norm = matplotlib.colors.Normalize(vmin=0.25, vmax=1.75)

    #         for i, n_state in enumerate(sorted(fit_data.keys())):
    #             print(sorted(fit_data.keys()),"keys?")
    #             for j, ti in enumerate(fit_data[n_state]['t']):
    #                 color = cmap(norm(fit_data[n_state]['chi2/df'][j]))
    #                 y = gv.mean(fit_data[n_state]['y'][j])
    #                 yerr = gv.sdev(fit_data[n_state]['y'][j])

    #                 alpha = 0.05
    #                 if vary_start and ti == self.t_range[model_type][0]:
    #                     alpha=0.35
    #                 elif (not vary_start) and ti == self.t_range[model_type][1]:
    #                     alpha=0.35

    #                 plt.axvline(ti-0.5, linestyle='--', alpha=alpha)
    #                 plt.axvline(ti+0.5, linestyle='--', alpha=alpha)

    #                 ti = ti + spacing[i]
    #                 plt.errorbar(ti, y, xerr = 0.0, yerr=yerr, fmt=markers[i%len(markers)], mec='k', mfc='white', ms=10.0,
    #                     capsize=5.0, capthick=1.0, elinewidth=5.0, alpha=0.9, ecolor=color, label=r"$N$=%s"%n_state)


    #         # Band for best result

    #         best_fit = self.get_fit()
    #         y_best = best_fit.p[corr+'_E0']
    #         ylabel = r'$E_0$'

    #         tp = np.arange(t[0]-1, t[-1]+2)
    #         tlim = (tp[0], tp[-1])

    #         pm = lambda x, k : gv.mean(x) + k*gv.sdev(x)
    #         y2 = np.repeat(pm(y_best, 0), len(tp))
    #         y2_upper = np.repeat(pm(y_best, 1), len(tp))
    #         y2_lower = np.repeat(pm(y_best, -1), len(tp))

    #         # Ground state plot
    #         plt.plot(tp, y2, '--')
    #         plt.plot(tp, y2_upper, tp, y2_lower)
    #         plt.fill_between(tp, y2_lower, y2_upper, facecolor = 'yellow', alpha = 0.25)

    #         plt.ylabel(ylabel, fontsize=24)
    #         plt.xlim(tlim[0], tlim[-1])

    #         # Limit y-axis when comparing multiple states
    #         if n_states_array is not None:
    #             plt.ylim(pm(y_best, -5), pm(y_best, 5))

    #         # Get unique markers when making legend
    #         handles, labels = plt.gca().get_legend_handles_labels()
    #         temp = {}
    #         for j, handle in enumerate(handles):
    #             temp[labels[j]] = handle

    #         plt.legend([temp[label] for label in sorted(temp.keys())], [label for label in sorted(temp.keys())])

    #         ###
    #         # Set axes: next for Q-values
    #         axQ = plt.axes([0.10,0.10,0.7,0.10])

    #         for i, n_state in enumerate(sorted(fit_data.keys())):
    #             t = fit_data[n_state]['t']
    #             for ti in t:
    #                 alpha = 0.05
    #                 if vary_start and ti == self.t_range[model_type][0]:
    #                     alpha=0.35
    #                 elif (not vary_start) and ti == self.t_range[model_type][1]:
    #                     alpha=0.35

    #                 plt.axvline(ti-0.5, linestyle='--', alpha=alpha)
    #                 plt.axvline(ti+0.5, linestyle='--', alpha=alpha)


    #             t = t + spacing[i]
    #             y = gv.mean(fit_data[n_state]['Q'])
    #             yerr = gv.sdev(fit_data[n_state]['Q'])
    #             color_data = fit_data[n_state]['chi2/df']

    #             sc = plt.scatter(t, y, vmin=0.25, vmax=1.75, marker=markers[i%len(markers)], c=color_data, cmap=cmap)

    #         # Set labels etc
    #         plt.ylabel('$Q$', fontsize=24)
    #         plt.xlabel('$t$', fontsize=24)
    #         plt.ylim(-0.05, 1.05)
    #         plt.xlim(tlim[0], tlim[-1])

    #         axC = plt.axes([0.85,0.10,0.05,0.80])

    #         colorbar = matplotlib.colorbar.ColorbarBase(axC, cmap=cmap,
    #                                     norm=norm, orientation='vertical')
    #         colorbar.set_label(r'$\chi^2_\nu$', fontsize = 24)

    #         fig = plt.gcf()
    #         # plt.savefig(fig_name)
    #         if show_plot == True: plt.show()
    #         else: plt.close()

    #     return fig


    def return_best_fit_info(self,bs=None):
        plt.axis('off')
        # these are matplotlib.patch.Patch properties
        props = dict(boxstyle='round', facecolor='grey', alpha=0.5)

        # place a text box in upper left in axes coords
        #plt.text(0.05, 0.05, str(fit_ensemble.get_fit(fit_ensemble.best_fit_time_range[0], fit_ensemble.best_fit_time_range[1])),
        #fontsize=14, horizontalalignment='left', verticalalignment='bottom', bbox=props)
        text = self.__str__(bs=bs).expandtabs()
        plt.text(0.0, 1.0, str(text),
                 fontsize=10, ha='left', va='top', family='monospace', bbox=props)

        plt.tight_layout()
        fig = plt.gcf()
        plt.close()

        return fig

    def make_plots(self,model_type=None, fig_name = None,show_all=False):
        plots = np.array([])
        plots = np.append(self.return_best_fit_info(), plots)

        # Create a plot of best and stability plots
        #plots = np.append(plots, self.plot_all_fits())
        plots = np.append(plots, self.plot_effective_mass(t_plot_min=0,t_plot_max=20,model_type=model_type,fig_name=fig_name,show_fit=True))

        return plots

    def __str__(self,bs=None):
        output = "Model Type:" + str(self.model_type) 
        output = output+"\n"
        output = output+"\n"
        if bs:
            output = output +"\t bs: True" 
        output = output+"\n"
        # if self.corr_gv is not None:
        output = output + "\t N_{corr} = "+str(self.n_states[self.model_type])+"\t"
        output = output+"\n"
        # # if self.corr_gv is not None:
        # output = output + "\t t_{corr} = "+str(self.t_range[self.model_type])
        # output = output+"\n"
        output += "Fit results: \n"

        # temp_fit = self.get_fit()
        return output
        # return output + str(temp_fit)

