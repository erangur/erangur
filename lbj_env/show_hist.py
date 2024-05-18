import matplotlib.pyplot as plt

# Function to read data from a file
def read_data_from_file(filename):
    with open(filename, 'r') as file:
        data = [int(line.strip()) for line in file if line.strip()]
    return data

# Read data from 'multipliers_histogram.txt'
data = read_data_from_file('multipliers_histogram.txt')

# Plot the histogram
plt.hist(data, bins=range(min(data), max(data) + 2), edgecolor='black', align='left')

# Add titles and labels
plt.title('Histogram of Frequencies')
plt.xlabel('Value')
plt.ylabel('Frequency')

# Show the plot
plt.show()

