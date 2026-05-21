import sys
import matplotlib.scale as mscale
import numpy as np
import matplotlib.ticker as ticker
import matplotlib.transforms as mtransforms
from statsmodels.distributions.empirical_distribution import ECDF
from scipy.stats import norm
from PySide6.QtWidgets import QApplication
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import math
import copy


def is_float(value):
    try:
        float_value = float(value)
        return not math.isnan(float_value)
    except ValueError:
        return False

class ProbabilityScale(mscale.ScaleBase):
    name = 'prob_scale'

    def __init__(self, axis, **kwargs):
        mscale.ScaleBase.__init__(self, axis)

    def get_transform(self):
        return self.ProbabilityTransform()

    def set_default_locators_and_formatters(self, axis):

        percentiles = np.array([0.01, 0.1, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.9, 99.99, 100]) / 100
        axis.set_major_locator(ticker.FixedLocator(percentiles))
        # axis.set_minor_locator(ticker.AutoMinorLocator(2))
        axis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f'{x * 100:.2f}%'))

    class ProbabilityTransform(mtransforms.Transform):
        input_dims = 1
        output_dims = 1
        is_separable = True

        def transform_non_affine(self, a):
            return norm.ppf(np.clip(a, 0.00001, 0.99999))

        def inverted(self):
            return ProbabilityScale.InvertedProbabilityTransform()

    class InvertedProbabilityTransform(mtransforms.Transform):
        input_dims = 1
        output_dims = 1
        is_separable = True

        def transform_non_affine(self, a):
            return norm.cdf(a)

        def inverted(self):
            return ProbabilityScale.ProbabilityTransform()


# Register the custom scale
mscale.register_scale(ProbabilityScale)


class PlotCanvas(FigureCanvas):

    def __init__(self, parent=None, width=5, height=3, dpi=200):

        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.fig.tight_layout()
        self.tp_name = ''
        self.plot_item = ''
        self.save_path = ''
        self.spec_sbin = None
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)

        self.colors = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
            "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
            "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
            "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
            "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173",
            "#a55194", "#8c564b", "#bd9e39", "#8c6d31", "#e7ba52",
            "#393b79", "#637939", "#8c6d31", "#d6616b", "#843c39",
            "#a55194", "#d8b365", "#7b4173", "#b5cf6b", "#843c39",
            "#bcbd22", "#17becf", "#7f7f7f", "#c5b0d5", "#ff9896",
            "#98df8a", "#ffbb78", "#aec7e8", "#ff7f0e", "#1f77b4",
            "#9edae5", "#c49c94", "#f7b6d2", "#c7c7c7", "h#dbdb8d"
        ]
        self.markers = ['o', '^', 's', 'p', '*', 'h', 'H', 'x', 'D', 'd', '|', '_', 'P', 'X']

        self.axes.set_yscale('prob_scale')
        self.axes.set_ylim(0, 1)
        self.axes.tick_params(axis='both', labelsize=5.2)
        self.axes.grid(True)

        self.selected_wafer_list = []
        self.selected_wafer_data = []
        self.selected_data = []
        self.lines = []
        self.spec_ = []
        self.testflow_name = ''
        self.wafer_name = ''
        self.spec_rule = ''
        self.title_font_size = 7
        self.group_flag = False
        self.lower_line = None
        self.upper_line = None
        self.upper_line_value = None
        self.lower_line_value = None
        # =====
        self.data_dict = {}

    def init_pchart_plot(self):
        try:
            self.axes.clear()
            self.selected_wafer_data = []
            self.selected_data = []

            title_item_name = self.plot_item.replace(f'{self.testflow_name}_', '')

            if self.spec_rule == '':

                print('spec rule is none')
                self.plot_item = copy.deepcopy(self.testflow_name)

                self.axes.set_title(f'SBIN{self.spec_sbin} {self.tp_name}\n{self.wafer_name}  {self.plot_item}',
                                    fontsize=self.title_font_size)
                self.axes.set_yscale('prob_scale')
                self.axes.set_ylim(0, 1)
                self.axes.tick_params(axis='both', labelsize=6)
                self.axes.grid(True)
                self.draw()
                return

            if self.spec_rule in ['Exist', 'Equal']:
                self.axes.set_title(f'SBIN{self.spec_sbin} {self.tp_name}\n{self.wafer_name}  {self.plot_item}',
                                    fontsize=self.title_font_size)
                self.axes.set_yscale('prob_scale')
                self.axes.set_ylim(0, 1)
                self.axes.tick_params(axis='both', labelsize=6)
                self.axes.grid(True)
                self.draw()
                return

            for num, (wafer_name, info) in enumerate(self.data_dict.items()):
                plot_data_name = wafer_name
                for tp_name, data_ in info['TP'].items():

                    self.wafer_name = wafer_name
                    if self.plot_item in list(data_['Data']):
                        plot_data = data_['Data'][self.plot_item].tolist()

                        plot_data = [float(x) for x in plot_data if is_float(x)]
                        plot_data = [item for item in plot_data if item != 'None']
                        plot_data.sort()

                        self.selected_data += plot_data
                        self.selected_wafer_data.append([plot_data_name, plot_data, True])
                        cumprob = ECDF(plot_data)(plot_data)

                        line_color = self.colors[num % len(self.colors)]
                        line, = self.axes.step(plot_data, cumprob, where='post',
                                               color=line_color,
                                               marker=self.markers[num % len(self.markers)], alpha=0.7, markersize=1,
                                               label=f'{plot_data_name}', visible=True)
                    else:

                        line, = self.axes.step([], [], visible=False)

                    self.lines.append(line)

            # calculate_fail count()

            total_count, total_fail_count, gain_yield = calculate_fail_count(self.selected_data, self.spec_rule,
                                                                self.spec_[0], self.spec_[1])

            # add text for fail count

            self.axes.text(
                0.79, 0.02,
                f"Total: {total_count}\nFail: {total_fail_count}\nYield: {gain_yield}",
                transform=self.axes.transAxes,
                ha='left',  # 字體靠左
                va='bottom',
                fontsize=9,
                color='black',
                bbox=dict(
                    facecolor='white',
                    edgecolor='lightgray',
                    alpha=0.6,
                    boxstyle='round,pad=0.3'
                )
            )

            if self.spec_rule == 'Pass/Fail':
                self.upper_line_value = 1
                self.lower_line_value = 0
            else:
                self.upper_line_value = self.spec_[1]
                self.lower_line_value = self.spec_[0]

            if self.upper_line_value != 'None':
                self.upper_line = self.axes.axvline(x=float(self.upper_line_value), color='red', linestyle='--',
                                                    label=f'Upper limit = {self.upper_line_value}')

            if self.lower_line_value != 'None':
                self.lower_line = self.axes.axvline(x=float(self.lower_line_value), color='blue', linestyle='--',
                                                    label=f'Lower limit = {self.lower_line_value}')

            self.axes.set_yscale('prob_scale')
            self.axes.set_ylim(0, 1)
            self.axes.tick_params(axis='both', labelsize=6)
            self.axes.grid(True)

            self.data_min = np.nanmin(self.selected_data)
            self.data_max = np.nanmax(self.selected_data)
            self.data_median = np.median(self.selected_data)
            self.data_p99 = np.median(self.selected_data)
            self.data_p1 = np.median(self.selected_data)

            p75 = np.percentile(self.selected_data, 75)  # P75
            p50 = np.percentile(self.selected_data, 50)  # P50
            p25 = np.percentile(self.selected_data, 25)  # P25

            self.axes.set_title(f'SBIN{self.spec_sbin} {self.testflow_name}\n{title_item_name}',
                                fontsize=self.title_font_size)

            if self.spec_rule == 'InRange':
                delta = abs(float(self.upper_line_value) - float(self.lower_line_value)) * 0.2

                self.axes.set_xlim([float(self.lower_line_value) - delta, float(self.upper_line_value) + delta])

            elif self.spec_rule in ['Less', 'LessEqual']:
                delta = abs(float(self.upper_line_value) - self.data_min) * 0.2
                half_range = abs(float(self.upper_line_value) - p50) + delta
                self.axes.set_xlim([p50 - half_range, float(self.upper_line_value) + delta])

            elif self.spec_rule in ['Greater', 'GreaterEqual']:
                delta = abs(float(self.lower_line_value) - self.data_max) * 0.2

                half_range = abs(float(self.lower_line_value) + p50) + delta

                self.axes.set_xlim([float(self.lower_line_value) - delta, p50 + half_range])

            elif self.spec_rule == 'Pass/Fail':
                self.axes.set_xlim(-1, 2)
            else:
                delta = p75 - p25

                self.axes.set_xlim(float(p25) - delta, float(p75) + delta)

            self.axes.legend(loc='upper left', prop={'size': 6})
            self.draw()

        except Exception as e:
            print(f'Pchart error on : {e}')

    def export_image(self):

        full_save_path = f"{self.save_path}\\{self.plot_item}~SBIN{int(self.spec_sbin)}.png"

        if len(full_save_path) >= 200:
            short_item_name = self.plot_item.replace(f'{self.testflow_name}_', '')
            subsitute_save_path = f"{self.save_path}\\{short_item_name}~SBIN{int(self.spec_sbin)}.png"
            self.fig.savefig(subsitute_save_path)
        else:
            self.fig.savefig(full_save_path)

        return


def calculate_fail_count(data_list, spec_rule, spec_l, spec_h):
    total_fail_count = 0

    if spec_rule == 'InRange':
        for value in data_list:
            try:
                v = float(value)
                if not (float(spec_l) <= v <= float(spec_h)):
                    total_fail_count += 1
            except (ValueError, TypeError):
                # 無法轉成 float 的項目也視為 fail
                total_fail_count += 1

    elif spec_rule == 'LessEqual':
        for value in data_list:
            try:
                v = float(value)
                if not v <= float(spec_h):
                    total_fail_count += 1
            except (ValueError, TypeError):
                total_fail_count += 1

    elif spec_rule == 'Less':
        for value in data_list:
            try:
                v = float(value)
                if not v < float(spec_h):
                    total_fail_count += 1
            except (ValueError, TypeError):
                total_fail_count += 1

    elif spec_rule == 'GreaterEqual':
        for value in data_list:
            try:
                v = float(value)
                if not v >= float(spec_l):
                    total_fail_count += 1
            except (ValueError, TypeError):
                total_fail_count += 1

    elif spec_rule == 'Greater':
        for value in data_list:
            try:
                v = float(value)
                if not v > float(spec_l):
                    total_fail_count += 1
            except (ValueError, TypeError):
                total_fail_count += 1

    elif spec_rule == 'Pass/Fail':
        for value in data_list:
            try:
                v = float(value)
                if v != float(spec_l):
                    total_fail_count += 1

            except (ValueError, TypeError):
                total_fail_count += 1

    yield_ = total_fail_count / len(data_list) * 100
    yield_str = str(round(yield_, 2)) + '%'

    return len(data_list), total_fail_count, yield_str


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = PlotCanvas()  # load data & init it
    ex.show()
    sys.exit(app.exec())
