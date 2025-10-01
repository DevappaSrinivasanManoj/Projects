import tkinter as tk
from tkinter import ttk
import math
import stats
from fractions import Fraction

class ScientificCalculator:
    def __init__(self, root):
        self.root = root
        self.root.title("Scientific Calculator")

        # Create tabs for different calculations
        self.tab_control = ttk.Notebook(self.root)
        self.geometric_tab = ttk.Frame(self.tab_control)
        self.normal_tab = ttk.Frame(self.tab_control)
        self.binomial_tab = ttk.Frame(self.tab_control)
        self.poisson_tab = ttk.Frame(self.tab_control)
        self.exponential_tab = ttk.Frame(self.tab_control)
        self.uniform_tab = ttk.Frame(self.tab_control)
        self.normal_to_lognormal_tab = ttk.Frame(self.tab_control)
        self.lognormal_to_normal_tab = ttk.Frame(self.tab_control)

        self.tab_control.add(self.geometric_tab, text="Geometric")
        self.tab_control.add(self.normal_tab, text="Normal")
        self.tab_control.add(self.binomial_tab, text="Binomial")
        self.tab_control.add(self.poisson_tab, text="Poisson")
        self.tab_control.add(self.exponential_tab, text="Exponential")
        self.tab_control.add(self.uniform_tab, text="Uniform")
        self.tab_control.add(self.normal_to_lognormal_tab, text="Normal to Lognormal")
        self.tab_control.add(self.lognormal_to_normal_tab, text="Lognormal to Normal")

        self.tab_control.pack(expand=1, fill="both")

        # Create UI for geometric distribution
        self.create_geometric_ui()

        # Create UI for normal distribution
        self.create_normal_ui()

        # Create UI for binomial distribution
        self.create_binomial_ui()

        # Create UI for poisson distribution
        self.create_poisson_ui()

        # Create UI for exponential distribution
        self.create_exponential_ui()

        # Create UI for uniform distribution
        self.create_uniform_ui()

        # Create UI for normal to lognormal conversion
        self.create_normal_to_lognormal_ui()

        # Create UI for lognormal to normal conversion
        self.create_lognormal_to_normal_ui()

    def create_geometric_ui(self):
        # Create UI for geometric distribution
        geometric_label = tk.Label(self.geometric_tab, text="Geometric Distribution")
        geometric_label.pack()

        probability_label = tk.Label(self.geometric_tab, text="Probability of success:")
        probability_label.pack()
        self.geometric_probability_entry = tk.Entry(self.geometric_tab)
        self.geometric_probability_entry.pack()

        number_of_trials_label = tk.Label(self.geometric_tab, text="Number of trials:")
        number_of_trials_label.pack()
        self.geometric_number_of_trials_entry = tk.Entry(self.geometric_tab)
        self.geometric_number_of_trials_entry.pack()

        calculate_button = tk.Button(self.geometric_tab, text="Calculate", command=self.calculate_geometric)
        calculate_button.pack()

        self.geometric_result_label = tk.Label(self.geometric_tab, text="")
        self.geometric_result_label.pack()

    def create_normal_ui(self):
        # Create UI for normal distribution
        normal_label = tk.Label(self.normal_tab, text="Normal Distribution")
        normal_label.pack()

        mean_label = tk.Label(self.normal_tab, text="Mean:")
        mean_label.pack()
        self.normal_mean_entry = tk.Entry(self.normal_tab)
        self.normal_mean_entry.pack()

        standard_deviation_label = tk.Label(self.normal_tab, text="Standard Deviation:")
        standard_deviation_label.pack()
        self.normal_standard_deviation_entry = tk.Entry(self.normal_tab)
        self.normal_standard_deviation_entry.pack()

        x_label = tk.Label(self.normal_tab, text="x:")
        x_label.pack()
        self.normal_x_entry = tk.Entry(self.normal_tab)
        self.normal_x_entry.pack()

        calculate_button = tk.Button(self.normal_tab, text="Calculate", command=self.calculate_normal)
        calculate_button.pack()

        self.normal_result_label = tk.Label(self.normal_tab, text="")
        self.normal_result_label.pack()

    def create_binomial_ui(self):
        # Create UI for binomial distribution
        binomial_label = tk.Label(self.binomial_tab, text="Binomial Distribution")
        binomial_label.pack()

        number_of_trials_label = tk.Label(self.binomial_tab, text="Number of trials:")
        number_of_trials_label.pack()
        self.binomial_number_of_trials_entry = tk.Entry(self.binomial_tab)
        self.binomial_number_of_trials_entry.pack()

        probability_label = tk.Label(self.binomial_tab, text="Probability of success:")
        probability_label.pack()
        self.binomial_probability_entry = tk.Entry(self.binomial_tab)
        self.binomial_probability_entry.pack()

        number_of_successes_label = tk.Label(self.binomial_tab, text="Number of successes:")
        number_of_successes_label.pack()
        self.binomial_number_of_successes_entry = tk.Entry(self.binomial_tab)
        self.binomial_number_of_successes_entry.pack()

        calculate_button = tk.Button(self.binomial_tab, text="Calculate", command=self.calculate_binomial)
        calculate_button.pack()

        self.binomial_result_label = tk.Label(self.binomial_tab, text="")
        self.binomial_result_label.pack()

    def create_poisson_ui(self):
        # Create UI for poisson distribution
        poisson_label = tk.Label(self.poisson_tab, text="Poisson Distribution")
        poisson_label.pack()

        mean_label = tk.Label(self.poisson_tab, text="Mean:")
        mean_label.pack()
        self.poisson_mean_entry = tk.Entry(self.poisson_tab)
        self.poisson_mean_entry.pack()

        number_of_occurrences_label = tk.Label(self.poisson_tab, text="Number of occurrences:")
        number_of_occurrences_label.pack()
        self.poisson_number_of_occurrences_entry = tk.Entry(self.poisson_tab)
        self.poisson_number_of_occurrences_entry.pack()

        calculate_button = tk.Button(self.poisson_tab, text="Calculate", command=self.calculate_poisson)
        calculate_button.pack()

        self.poisson_result_label = tk.Label(self.poisson_tab, text="")
        self.poisson_result_label.pack()

    def create_exponential_ui(self):
        # Create UI for exponential distribution
        exponential_label = tk.Label(self.exponential_tab, text="Exponential Distribution")
        exponential_label.pack()

        scale_label = tk.Label(self.exponential_tab, text="Scale:")
        scale_label.pack()
        self.exponential_scale_entry = tk.Entry(self.exponential_tab)
        self.exponential_scale_entry.pack()

        x_label = tk.Label(self.exponential_tab, text="x:")
        x_label.pack()
        self.exponential_x_entry = tk.Entry(self.exponential_tab)
        self.exponential_x_entry.pack()

        calculate_button = tk.Button(self.exponential_tab, text="Calculate", command=self.calculate_exponential)
        calculate_button.pack()

        self.exponential_result_label = tk.Label(self.exponential_tab, text="")
        self.exponential_result_label.pack()

    def create_uniform_ui(self):
        # Create UI for uniform distribution
        uniform_label = tk.Label(self.uniform_tab, text="Uniform Distribution")
        uniform_label.pack()

        lower_bound_label = tk.Label(self.uniform_tab, text="Lower bound:")
        lower_bound_label.pack()
        self.uniform_lower_bound_entry = tk.Entry(self.uniform_tab)
        self.uniform_lower_bound_entry.pack()

        upper_bound_label = tk.Label(self.uniform_tab, text="Upper bound:")
        upper_bound_label.pack()
        self.uniform_upper_bound_entry = tk.Entry(self.uniform_tab)
        self.uniform_upper_bound_entry.pack()

        x_label = tk.Label(self.uniform_tab, text="x:")
        x_label.pack()
        self.uniform_x_entry = tk.Entry(self.uniform_tab)
        self.uniform_x_entry.pack()

        calculate_button = tk.Button(self.uniform_tab, text="Calculate", command=self.calculate_uniform)
        calculate_button.pack()

        self.uniform_result_label = tk.Label(self.uniform_tab, text="")
        self.uniform_result_label.pack()

    def create_normal_to_lognormal_ui(self):
        # Create UI for normal to lognormal conversion
        normal_to_lognormal_label = tk.Label(self.normal_to_lognormal_tab, text="Normal to Lognormal")
        normal_to_lognormal_label.pack()

        mean_label = tk.Label(self.normal_to_lognormal_tab, text="Mean:")
        mean_label.pack()
        self.normal_to_lognormal_mean_entry = tk.Entry(self.normal_to_lognormal_tab)
        self.normal_to_lognormal_mean_entry.pack()

        variance_label = tk.Label(self.normal_to_lognormal_tab, text="Variance:")
        variance_label.pack()
        self.normal_to_lognormal_variance_entry = tk.Entry(self.normal_to_lognormal_tab)
        self.normal_to_lognormal_variance_entry.pack()

        calculate_button = tk.Button(self.normal_to_lognormal_tab, text="Calculate", command=self.calculate_normal_to_lognormal)
        calculate_button.pack()

        self.normal_to_lognormal_result_label = tk.Label(self.normal_to_lognormal_tab, text="")
        self.normal_to_lognormal_result_label.pack()

    def create_lognormal_to_normal_ui(self):
        # Create UI for lognormal to normal conversion
        lognormal_to_normal_label = tk.Label(self.lognormal_to_normal_tab, text="Lognormal to Normal")
        lognormal_to_normal_label.pack()

        mean_label = tk.Label(self.lognormal_to_normal_tab, text="Mean:")
        mean_label.pack()
        self.lognormal_to_normal_mean_entry = tk.Entry(self.lognormal_to_normal_tab)
        self.lognormal_to_normal_mean_entry.pack()

        variance_label = tk.Label(self.lognormal_to_normal_tab, text="Variance:")
        variance_label.pack()
        self.lognormal_to_normal_variance_entry = tk.Entry(self.lognormal_to_normal_tab)
        self.lognormal_to_normal_variance_entry.pack()

        calculate_button = tk.Button(self.lognormal_to_normal_tab, text="Calculate", command=self.calculate_lognormal_to_normal)
        calculate_button.pack()

        self.lognormal_to_normal_result_label = tk.Label(self.lognormal_to_normal_tab, text="")
        self.lognormal_to_normal_result_label.pack()

    def calculate_geometric(self):
        probability = float(self.geometric_probability_entry.get())
        number_of_trials = float(self.geometric_number_of_trials_entry.get())
        result = stats.geom.pmf(number_of_trials, probability)
        self.geometric_result_label.config(text=f"Result: {result}")

    def calculate_normal(self):
        mean = float(self.normal_mean_entry.get())
        standard_deviation = float(self.normal_standard_deviation_entry.get())
        x = float(self.normal_x_entry.get())
        result = stats.norm.pdf(x, mean, standard_deviation)
        self.normal_result_label.config(text=f"Result: {result}")

    def calculate_binomial(self):
        number_of_trials = float(self.binomial_number_of_trials_entry.get())
        probability = float(self.binomial_probability_entry.get())
        number_of_successes = float(self.binomial_number_of_successes_entry.get())
        result = stats.binom.pmf(number_of_successes, number_of_trials, probability)
        self.binomial_result_label.config(text=f"Result: {result}")

    def calculate_poisson(self):
        mean = float(self.poisson_mean_entry.get())
        number_of_occurrences = float(self.poisson_number_of_occurrences_entry.get())
        result = stats.poisson.pmf(number_of_occurrences, mean)
        self.poisson_result_label.config(text=f"Result: {result}")

    def calculate_exponential(self):
        scale = float(self.exponential_scale_entry.get())
        x = float(self.exponential_x_entry.get())
        result = stats.expon.pdf(x, scale=scale)
        self.exponential_result_label.config(text=f"Result: {result}")

    def calculate_uniform(self):
        lower_bound = float(self.uniform_lower_bound_entry.get())
        upper_bound = float(self.uniform_upper_bound_entry.get())
        x = float(self.uniform_x_entry.get())
        result = stats.uniform.pdf(x, loc=lower_bound, scale=upper_bound-lower_bound)
        self.uniform_result_label.config(text=f"Result: {result}")

    def calculate_normal_to_lognormal(self):
        mean = float(self.normal_to_lognormal_mean_entry.get())
        variance = float(self.normal_to_lognormal_variance_entry.get())
        lognormal_mean = math.exp(mean + variance / 2)
        lognormal_variance = (math.exp(variance) - 1) * math.exp(2 * mean + variance)
        self.normal_to_lognormal_result_label.config(text=f"Lognormal Mean: {lognormal_mean}, Lognormal Variance: {lognormal_variance}")

    def calculate_lognormal_to_normal(self):
        mean = float(self.lognormal_to_normal_mean_entry.get())
        variance = float(self.lognormal_to_normal_variance_entry.get())
        normal_mean = math.log(mean / math.sqrt(1 + variance / (mean ** 2)))
        normal_variance = math.log(1 + variance / (mean ** 2))
        self.lognormal_to_normal_result_label.config(text=f"Normal Mean: {normal_mean}, Normal Variance: {normal_variance}")


if __name__ == "__main__":
    root = tk.Tk()
    calculator = ScientificCalculator(root)
    root.mainloop()
