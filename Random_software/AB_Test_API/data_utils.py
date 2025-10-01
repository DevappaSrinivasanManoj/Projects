import random

def sample_data(data, n=1000):
    """Randomly sample n elements from the data."""
    return random.sample(data, min(n, len(data)))

def is_paired(data1, data2, paired=False):
    """Check if data is paired. Default is unpaired."""
    return paired and len(data1) == len(data2)
