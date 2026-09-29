source 'https://rubygems.org'
source "https://gems.example.com/private"
gem 'from-default'
source 'https://gems.fury.io/acme' do
  gem 'from-block'
  group :test do
    gem 'block-and-group'
  end
end
gem 'option-source', source: 'http://localhost:9292'
source 'https://user:pw@gems.example.com/x' do
  gem 'with-credentials'
  gem 'own-source', source: 'https://other.example.com'
end
