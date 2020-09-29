from syconn.proc.stats import FileTimer
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
import os
import glob

palette_ident = 'colorblind'


def get_speed_plots():
    sns.set_style("ticks", {"xtick.major.size": 20, "ytick.major.size": 20})
    wds = glob.glob('/mnt/example_runs/j0251_*')
    base_dir = '/mnt/example_runs/timings/'
    os.makedirs(base_dir, exist_ok=True)
    res_dc = {'time': [], 'step': [], 'datasize[um3]': [], 'datasize[GVx]': [],
              'speed[um3]': [], 'speed[GVx]': []}

    # /mnt/example_runs/j0251_off9463_9579_5699_size8192_8192_4096_24nodes_run2 is currently the only WD with
    # probably reasonably outcome; PS 23Sep2020

    for wd in sorted(wds, key=lambda x: FileTimer(x).dataset_mm3):
        if wd in ['/mnt/example_runs/j0251_off7415_7531_4675_size12288_12288_6144_24nodes',
                  '/mnt/example_runs/j0251_off10999_11115_6467_size5120_5120_2560_24nodes']:  # not done
            continue
        ft = FileTimer(wd, add_detail_vols=True)
        print(ft.working_dir, ft.prepare_report())
        print(ft.dataset_mm3, ft.dataset_nvoxels)
        # no reasonable volume information for these steps:
        for name in ['Preparation', 'Matrix export', 'Spine head calculation', 'Glia splitting']:
            del ft.timings[name]
        for name, dt in ft.timings.items():
            dt = dt / 3600
            res_dc['time'].append(dt)
            res_dc['step'].append(name)
            res_dc['datasize[um3]'].append(ft.dataset_mm3['cube'])
            res_dc['datasize[GVx]'].append(ft.dataset_nvoxels['cube'])
            # use actually processed volums (e.g. all for synapses, glia-free rag for cell type inference)
            if 'glia' in name.lower():
                vol_mm3 = ft.dataset_mm3['neuron'] + ft.dataset_mm3['glia']
                vol_nvox = ft.dataset_nvoxels['neuron'] + ft.dataset_nvoxels['glia']
            elif name in ['SD generation', 'Synapse detection', 'Skeleton generation']:
                vol_mm3 = ft.dataset_mm3['cube']
                vol_nvox = ft.dataset_nvoxels['cube']
            else:
                vol_mm3 = ft.dataset_mm3['neuron']
                vol_nvox = ft.dataset_nvoxels['neuron']
            res_dc['speed[um3]'].append(vol_mm3 / dt)
            res_dc['speed[GVx]'].append(vol_nvox / dt)
    assert len(wds) > 0
    df = pd.DataFrame(data=res_dc)
    df.to_csv(f'{base_dir}/data_speed.csv')
    fmt = '{:0.2f}'
    # Speed bar plot
    plt.figure()
    axes = sns.barplot(data=df, x="datasize[GVx]", y="speed[GVx]", hue="step", palette=palette_ident)
    axes.legend(*axes.get_legend_handles_labels(), bbox_to_anchor=(1.05, 1),
                loc='upper left', borderaxespad=0.)
    axes.set_ylabel('speed [GVx / h]')
    axes.set_xlabel('size [GVx]')
    xticklabels = []
    for item in axes.get_xticklabels():
        item.set_text(fmt.format(float(item.get_text())))
        xticklabels += [item]
    axes.set_xticklabels(xticklabels)
    plt.subplots_adjust(right=0.75)
    plt.savefig(base_dir + '/speed_barplot.png')
    plt.close()

    # Speed scatter plot
    plt.figure()
    axes = sns.scatterplot(data=df, x="datasize[GVx]", y="speed[GVx]", hue="step", palette=palette_ident)
    axes.legend(*axes.get_legend_handles_labels(), bbox_to_anchor=(1.05, 1),
                loc='upper left', borderaxespad=0.)
    axes.set_ylabel('speed [GVx / h]')
    axes.set_xlabel('size [GVx]')
    plt.subplots_adjust(right=0.75)
    plt.savefig(base_dir + '/speed_pointplot.png')
    plt.close()
    print('\n-----------------------------------------------------------\n')


def get_timing_plots():
    sns.set_style("ticks", {"xtick.major.size": 20, "ytick.major.size": 20})
    wds = glob.glob('/mnt/example_runs/j0251_*')
    base_dir = '/mnt/example_runs/timings/'
    os.makedirs(base_dir, exist_ok=True)
    res_dc = {'time': [], 'time_rel': [], 'step': [], 'datasize[um3]': [], 'datasize[GVx]': []}

    # /mnt/example_runs/j0251_off9463_9579_5699_size8192_8192_4096_24nodes_run2 is currently the only WD with
    # probably reasonably outcome; PS 23Sep2020

    for wd in sorted(wds, key=lambda x: FileTimer(x).dataset_mm3):
        if wd in ['/mnt/example_runs/j0251_off7415_7531_4675_size12288_12288_6144_24nodes',
                  '/mnt/example_runs/j0251_off10999_11115_6467_size5120_5120_2560_24nodes']:  # not done
            continue
        ft = FileTimer(wd, add_detail_vols=False)
        print(ft.working_dir, ft.prepare_report())
        dt_tot = np.sum([ft.timings[k] for k in ft.timings if not ('multiv-view' in k) and not ('multi-view' in k)])
        dt_views = np.sum([ft.timings[k] for k in ft.timings if ('multiv-view' in k) or ('multi-view' in k) or
                           (k == 'Glia splitting')])
        dt_points = np.sum([ft.timings[k] for k in ft.timings if ('points' in k) or (k == 'Glia splitting')])
        dt_database = np.sum(
            [ft.timings[k] for k in ['SD generation', 'SSD generation', 'Preparation', 'Skeleton generation']])
        dt_syns = np.sum([ft.timings[k] for k in ['Synapse detection']])
        dt_syn_enrich = np.sum([ft.timings[k] for k in ['Spine head calculation', 'Matrix export']])
        assert np.isclose(dt_tot, dt_points + dt_database + dt_syns + dt_syn_enrich)
        print(ft.dataset_mm3, ft.dataset_nvoxels)
        print(f'Time points to views: {dt_points / dt_views}')
        print(f'Total time (using points): {dt_points + dt_database + dt_syns}')
        for name, dt in [('total', dt_tot), ('views', dt_views), ('points', dt_points),
                         ('data structure', dt_database), ('synapses', dt_syns), ('synapse enrichment', dt_syn_enrich)]:
            dt = dt / 3600
            res_dc['time'].append(dt)
            res_dc['time_rel'].append(dt / dt_tot * 100)
            res_dc['step'].append(name)
            res_dc['datasize[um3]'].append(ft.dataset_mm3)
            res_dc['datasize[GVx]'].append(ft.dataset_nvoxels)
    assert len(wds) > 0
    df = pd.DataFrame(data=res_dc)
    df.to_csv(f'{base_dir}/data_timings.csv')
    fmt = '{:0.2f}'

    # Time bar plot
    plt.figure()

    axes = sns.barplot(data=df, x="datasize[GVx]", y="time", hue="step", palette=palette_ident)
    axes.legend(*axes.get_legend_handles_labels(), bbox_to_anchor=(1.05, 1),
                loc='upper left', borderaxespad=0.)
    axes.set_ylabel('Time [h]')
    axes.set_xlabel('size [GVx]')
    xticklabels = []
    for item in axes.get_xticklabels():
        item.set_text(fmt.format(float(item.get_text())))
        xticklabels += [item]
    axes.set_xticklabels(xticklabels)
    plt.subplots_adjust(right=0.75)
    plt.savefig(base_dir + '/time_barplot.png')
    plt.close()

    # Time scatter plot
    plt.figure()
    axes = sns.scatterplot(data=df, x="datasize[GVx]", y="time", hue="step", palette=palette_ident)
    axes.legend(*axes.get_legend_handles_labels(), bbox_to_anchor=(1.05, 1),
                loc='upper left', borderaxespad=0.)
    axes.set_ylabel('time [h]')
    axes.set_xlabel('size [GVx]')
    plt.subplots_adjust(right=0.75)
    plt.savefig(base_dir + '/time_pointplot.png')
    plt.close()

    # Total time regression plot
    import statsmodels.api as sm
    x = [df['datasize[GVx]'][ii] for ii in range(len(df['datasize[GVx]'])) if df['step'][ii] == 'total']
    y = [df['time'][ii] for ii in range(len(df['datasize[GVx]'])) if df['step'][ii] == 'total']
    mod = sm.OLS(y, x)
    res = mod.fit()
    print(res.summary())
    x_fit = np.linspace(np.min(x), np.max(x), 1000)
    y_fit = res.params[0] * x_fit
    plt.figure()
    # https://seaborn.pydata.org/generated/seaborn.regplot.html
    axes = sns.scatterplot(x=x, y=y, palette=palette_ident)
    axes.legend(*axes.get_legend_handles_labels(), bbox_to_anchor=(1.05, 1),
                loc='upper left', borderaxespad=0.)
    plt.plot(x_fit, y_fit)
    axes.set_ylabel('time [h]')
    axes.set_xlabel('size [GVx]')
    plt.subplots_adjust(right=0.75)
    plt.savefig(base_dir + '/totaltime_regplot.png')
    plt.close()

    # stacked bar plot
    steps = ['points', 'data structure', 'synapses']  # ['views']
    palette = sns.color_palette(n_colors=len(steps), palette=palette_ident)
    f, ax = plt.subplots()
    bar_plts = []
    x = [df['datasize[GVx]'][ii] for ii in range(len(df['datasize[GVx]'])) if df['step'][ii] == 'total']
    ind = np.arange(len(x))
    width = 0.35
    cumulated_bar_vals = np.zeros((len(x)))
    for ii, step in enumerate(steps):

        y = np.array([df['time'][ii] for ii in range(len(df['datasize[GVx]'])) if df['step'][ii] == step])
        p = plt.bar(ind, y, width, bottom=cumulated_bar_vals, color=palette[ii], linewidth=0)  # yerr=None
        cumulated_bar_vals += y
        bar_plts.append(p[0])
    plt.legend(bar_plts, steps)
    plt.xticks(ind, [fmt.format(el) for el in x])
    ax.set_ylabel('Time [h]')
    ax.set_xlabel('size [GVx]')
    plt.subplots_adjust(right=0.75)
    plt.savefig(base_dir + '/time_stackedbarplot.png')
    plt.close()
    print('\n-----------------------------------------------------------\n')


if __name__ == '__main__':
    get_timing_plots()
    get_speed_plots()

