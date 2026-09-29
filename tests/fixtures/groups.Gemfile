gem 'plain'
group :development do
  gem 'pry'
  group :test do
    gem 'nested'
  end
end
group :test, :ci do
  gem 'two-groups'
end
group 'assets' do
  gem 'string-group'
end
group :docs, optional: true do
  gem 'yard'
end
gem 'opt', group: :staging
gem 'opts', groups: [:a, :b]
gem 'both', group: :x, groups: [:y]
group :production do
  gem 'mixed', group: :extra
end
group do
  gem 'empty-group-list'
end
