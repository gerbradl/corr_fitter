import lsqfit
import numpy as np 
import gvar as gv
import matplotlib
import matplotlib.pyplot as plt

class Fitter:
    '''
    The `Fitter` class is designed to fit models to hyperon data using least squares fitting.
    It takes in the prior information, raw correlator data, model information.
    '''

    def __init__(self, n_states,prior,t_range,states,
                 p_dict=None,raw_corrs=None,model_type=None,simult=None):
        self.n_states = n_states
        self.t_range = t_range
        self.prior = prior
        self.p_dict = p_dict
        self.raw_corrs = raw_corrs
        self.fit = None
        self.model_type = model_type
        self.simult = simult
        self.states = states
        self.prior = self._make_prior(prior)
        effective_mass = {}
        self.effective_mass = effective_mass


    def get_fit(self):
        if self.fit is not None:
            return self.fit
        return self._make_fit()

    def get_energies(self):
        # Don't rerun the fit if it's already been made
        if self.fit is not None:
            temp_fit = self.fit
        else:
            temp_fit = self.get_fit()

        max_n_states = np.max([self.n_states[key] for key in list(self.n_states.keys())])
        output = gv.gvar(np.zeros(max_n_states))
        output[0] = temp_fit.p['E0']
        for k in range(1, max_n_states):
            output[k] = output[0] + np.sum([(temp_fit.p['dE'][j]) for j in range(k)], axis=0)
        return output

    def _make_fit(self):
        '''first we create a model (which is a subclass of MultiFitter),
            Then we make a fitter using the models.
            Finally, we make the fit with our sets of correlators'''

        models = self._make_models_simult_fit()
        data = self._make_data()
        fitter_ = lsqfit.MultiFitter(models=models)
        fit = fitter_.lsqfit(data=data, prior=self.prior,fitter='scipy_least_squares')
        self.fit = fit
        return fit

    def _make_models_simult_fit(self):
        models = np.array([])

        if self.raw_corrs is not None:
            # corr = self.states
            datatag = self.states
            for sink in list(['SS','PS']):
                param_keys = {
                    'E0'      : datatag+'_E0',
                    'log(dE)' : 'log(dE_'+datatag+')',
                    'z_src' : datatag+'_z_'+sink[0],
                    'z_snk' : datatag+'_z_'+sink[1]

                }
                t = list(range(self.t_range[datatag][0], self.t_range[datatag][1]))

                models = np.append(models,
                        BaryonModel(datatag=datatag+"_"+sink,
                        t=t,param_keys=param_keys, n_states=self.n_states[self.model_type]))
        return models 

    # data array needs to match size of t array
    def _make_data(self):
        data = {}
        # for corr_type in ['lam', 'sigma', 'sigma_st', 'xi', 'xi_st','proton','delta']:
        corr_type = self.states
        for sinksrc in list(['SS','PS']):
            if self.simult:
                data[corr_type + '_' + sinksrc] = self.raw_corrs[corr_type][sinksrc][self.t_range[corr_type][0]:self.t_range[corr_type][1]]
            else:
                    data[corr_type + '_' + sinksrc] = self.raw_corrs[sinksrc][self.t_range[corr_type][0]:self.t_range[corr_type][1]]

        return data

    def _make_prior(self,prior):
        resized_prior = {}
        for key, value in prior.items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    resized_prior[subkey] = subvalue
            else:
                resized_prior[key] = value

        max_n_states = np.max([self.n_states[key] for key in list(self.n_states.keys())])
        # max_n_states = 4
        # for key in list(prior.keys()):
        #     for key in prior:
        #         print(f"{key}: {type(prior[key])}")

        #     resized_prior[key] = prior[key][:max_n_states]

        new_prior = resized_prior.copy()
        if self.simult:
            for corr in ['sigma','lam','xi','xi_st','sigma_st','proton','delta']:
                new_prior[corr+'_E0'] = resized_prior[corr+'_E'][0]
                new_prior.pop(corr+'_E', None)
                new_prior[corr+'_log(dE)'] = gv.gvar(np.zeros(len(resized_prior[corr+'_E']) - 1))
                pion_E_0  = gv.gvar(0.243, .01)
                for j in range(len(new_prior[corr+'_log(dE)'])):
                    temp_gvar = gv.gvar(np.log(2*pion_E_0.mean), 0.7)
                    # temp = gv.gvar(resized_prior[corr+'_E'][j+1]) - gv.gvar(resized_prior[corr+'_E'][j])
                    # temp2 = gv.gvar(resized_prior[corr+'_E'][j+1])
                    # temp_gvar = gv.gvar(temp.mean,temp2.sdev)
                    new_prior[corr+'_log(dE)'][j] = temp_gvar
        else:
            corr = self.states
            # for corr in list(self.states):
            #     print(corr)
            new_prior[corr+'_E0'] = resized_prior[corr+'_E'][0]
            new_prior.pop(corr+'_E', None)

    # We force the energy to be positive by using the log-normal dist of dE
    # let log(dE) ~ eta; then dE ~ e^eta
            pion_E_0  = gv.gvar(0.243, .01)
            temp_gvar = gv.gvar(np.log(2*pion_E_0.mean), 0.7)

            new_prior['log(dE_'+corr+')'] = gv.gvar(np.zeros(len(resized_prior[corr+'_E']) - 1))
            for j in range(len(new_prior['log(dE_'+corr+')'])):

                # temp = gv.gvar(resized_prior[corr+'_E'][j+1]) - gv.gvar(resized_prior[corr+'_E'][j])
                # temp2 = gv.gvar(resized_prior[corr+'_E'][j+1])
                # temp_gvar = gv.gvar(temp.mean,temp2.sdev)
                new_prior['log(dE_'+corr+')'][j] = temp_gvar

        def set_prior_Z(input_prior, p_key, n_states):
            m = gv.mean(input_prior[p_key])
            sd = gv.sdev(input_prior[p_key])
            k = 3
            return [gv.gvar(m, sd) if n==0 else gv.gvar(m, k *m) for n in range(n_states)]

        return new_prior

class BaryonModel(lsqfit.MultiFitterModel):
    def __init__(self, datatag, t, param_keys, n_states):
        super(BaryonModel, self).__init__(datatag)
        # variables for fit
        self.t = np.array(t)
        self.n_states = n_states
        # keys (strings) used to find the wf_overlap and energy in a parameter dictionary
        self.param_keys = param_keys

    def fitfcn(self, p, t=None):
        if t is None:
            t = self.t
        zz = p[self.param_keys['z_src']]* p[self.param_keys['z_snk']]
        E0 = p[self.param_keys['E0']]
        log_dE = p[self.param_keys['log(dE)']]
        output = zz[0] * np.exp(-E0 * t)
        for j in range(1, self.n_states):
            excited_state_energy = E0 + np.sum([np.exp(log_dE[k]) for k in range(j)], axis=0)
            output = output +zz[j] * np.exp(-excited_state_energy * t)
        return output

    def fcn_effective_mass(self, p, t=None):
        if t is None:
            t=self.t

        return np.log(self.fitfcn(p, t) / self.fitfcn(p, t+1))

    def fcn_effective_wf(self, p, t=None):
        if t is None:
            t=self.t
        t = np.array(t)
        
        return np.exp(self.fcn_effective_mass(p, t)*t) * self.fitfcn(p, t)

    def buildprior(self, prior, mopt=None, extend=False):
        ''' Extract the model's parameters from prior.'''
        return prior

    def builddata(self, data):
        ''' Key of data must match model's datatag'''
        return data[self.datatag]