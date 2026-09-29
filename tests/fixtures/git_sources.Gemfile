gem 'g1', git: 'https://github.com/acme/g1.git'
gem 'g2', git: 'git@github.com:acme/g2.git', branch: 'main'
gem 'g3', github: 'acme/g3', tag: 'v1.2.3'
gem 'g4', github: 'solo'
gem 'g5', gist: '12345'
gem 'g6', bitbucket: 'acme/g6'
gem 'g7', bitbucket: 'solo'
gem 'g8', git: 'https://example.com/g8.git', ref: 'abc123', submodules: true
gem 'g9', :git => 'https://example.com/g9.git', :branch => :develop
gem 'g10', '1.0.0', git: 'https://example.com/g10.git'
gem 'g11', '~> 1.0', github: 'acme/g11', glob: '*.gemspec'
git 'https://example.com/multi.git', branch: 'stable' do
  gem 'm1'
  gem 'm2', '2.0'
end
github 'acme/mono' do
  gem 'n1'
  gem 'n2', tag: 'v9'
end
