gem 'p1', path: '../p1'
gem 'p2', path: './vendor/p2/', glob: '*.gemspec'
gem 'p3', '1.0', path: 'vendor/p3'
path 'engines' do
  gem 'e1'
  gem 'e2', '~> 2.0'
end
path '../shared', glob: '{,*}.gemspec' do
  gem 'shared'
end
gem 'p4', path: 'a//b'
